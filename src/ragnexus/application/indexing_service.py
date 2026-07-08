"""IndexingService — 复用上传流水线的解析→分块→嵌入→双写逻辑。"""

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from ragnexus.core.logger import logger
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import Chunk, DocStatus, Document, ParsedDocument
from ragnexus.domain.ports import (
    DocumentPort,
    EmbedderPort,
    KeywordSearchPort,
    ParserPort,
    VectorStorePort,
)

if TYPE_CHECKING:
    from ragnexus.adapters.vector_store.pgvector import PgVectorStore


class IndexingService:
    """异步执行文档索引 — 解析→分块→嵌入→双写。"""

    def __init__(
        self,
        doc_repo: DocumentPort,
        parser: ParserPort,
        embedder: EmbedderPort,
        chunker: Callable[..., list[dict]],
        store: VectorStorePort,
        keyword_store: KeywordSearchPort | None = None,
        es_enabled: bool = False,
        chunk_max_chars: int = 1500,
        chunk_overlap: int = 50,
        parser_registry=None,  # 新增 — registry 用于二进制文件解析
        file_storage=None,  # 新增 — FileStoragePort 读取暂存文件
    ) -> None:
        self._doc_repo = doc_repo
        self._parser = parser
        self._embedder = embedder
        self._chunker = chunker
        self._store = store
        self._pg_store: PgVectorStore = store  # type: ignore[assignment]
        self._keyword_store = keyword_store
        self._es_enabled = es_enabled
        self._chunk_max_chars = chunk_max_chars
        self._chunk_overlap = chunk_overlap
        self._parser_registry = parser_registry
        self._file_storage = file_storage

    async def execute(self, doc_id: str) -> None:
        """执行索引流水线。幂等保护：非 PROCESSING 跳过。"""
        doc = await self._doc_repo.get(doc_id)
        if doc is None:
            logger.warning("索引任务: 文档不存在", extra={"doc_id": doc_id})
            return
        if doc.status != DocStatus.PROCESSING:
            logger.info(
                "索引任务: 跳过非 PROCESSING 文档",
                extra={"doc_id": doc_id, "status": doc.status.name},
            )
            return

        try:
            # 1. Parse — 分路径
            if doc.source_file_path and not doc.content.strip():
                # 二进制文件：registry parse → 更新 content
                parsed = await self._prepare_and_parse(doc)
            else:
                # 文本文件：现有行为
                parsed = await self._parser.parse(doc.content.encode(), doc.filename)
            if not parsed.sections and not parsed.raw_text:
                await self._doc_repo.update_status(
                    doc_id, status=DocStatus.FAILED, error_message="文件内容为空"
                )
                return

            # 2. Chunk
            chunk_dicts = self._chunker(
                parsed, max_chars=self._chunk_max_chars, overlap=self._chunk_overlap
            )
            if not chunk_dicts:
                await self._doc_repo.update_status(
                    doc_id, status=DocStatus.FAILED, error_message="分块结果为空"
                )
                return

            # 3. Embed
            texts = [cd["text"] for cd in chunk_dicts]
            vectors = await self._embedder.embed(texts)

            # 4. Build chunks
            common_meta = {
                "filename": doc.filename,
                "file_hash": doc.file_hash,
                "file_size": doc.file_size,
                "content_type": doc.content_type,
            }
            chunks = [
                Chunk(
                    id=f"{doc.doc_id}:{i}",
                    kb_id=doc.kb_id,
                    doc_id=doc.doc_id,
                    text=cd["text"],
                    vector=vectors[i],
                    metadata={
                        **common_meta,
                        "chunk_index": i,
                        "heading": cd.get("heading"),
                        "heading_level": cd.get("heading_level", 0),
                    },
                )
                for i, cd in enumerate(chunk_dicts)
            ]

            # 5. Dual write
            if self._es_enabled and self._keyword_store is not None:
                conn = await self._pg_store.acquire_connection()
                try:
                    es_task = asyncio.ensure_future(
                        self._keyword_store.upsert(doc.kb_id, chunks)
                    )
                    pg_task = asyncio.ensure_future(
                        self._pg_store._upsert_in_transaction(conn, doc.kb_id, chunks)
                    )
                    done, _ = await asyncio.wait(
                        [es_task, pg_task], return_when=asyncio.ALL_COMPLETED
                    )
                    es_ok = not es_task.exception()
                    pg_ok = not pg_task.exception()

                    if es_ok and pg_ok:
                        await conn.execute("COMMIT")
                    elif not es_ok and not pg_ok:
                        await conn.execute("ROLLBACK")
                        raise pg_task.exception()  # type: ignore[misc]
                    elif pg_ok and not es_ok:
                        await conn.execute("ROLLBACK")
                        raise es_task.exception()  # type: ignore[misc]
                    else:
                        # PG fail, ES ok → cleanup ES orphans
                        try:
                            ids = [c.id for c in chunks]
                            await self._keyword_store.delete(doc.kb_id, ids)
                        except Exception:
                            pass
                        await conn.execute("ROLLBACK")
                        raise pg_task.exception()  # type: ignore[misc]
                finally:
                    await self._pg_store.pool.release(conn)
            else:
                await self._store.upsert(doc.kb_id, chunks)

            # 6. Update to SUCCESS
            await self._doc_repo.update_status(
                doc_id, status=DocStatus.SUCCESS, chunk_count=len(chunks)
            )
            logger.info(
                "文档索引完成",
                extra={
                    "event_type": "BIZ_EVENT",
                    "event": "document_indexed",
                    "doc_id": doc_id,
                    "kb_id": doc.kb_id,
                    "chunks": len(chunks),
                },
            )

        except Exception as exc:
            logger.error(
                "文档索引失败",
                extra={
                    "event_type": "BIZ_EVENT",
                    "event": "document_index_failed",
                    "doc_id": doc_id,
                    "error": str(exc),
                },
            )
            await self._doc_repo.update_status(
                doc_id, status=DocStatus.FAILED, error_message=str(exc)[:500]
            )
            raise

    async def _prepare_and_parse(self, doc: Document) -> ParsedDocument:
        """从原始文件读取并解析二进制文档。

        1. 从 file_storage 读取原始字节
        2. 通过 registry 选择对应 parser
        3. 解析后更新 doc.content（供持久化查询）
        4. 返回 ParsedDocument
        """
        try:
            file_bytes = await self._file_storage.read(doc.source_file_path)
            parser = self._parser_registry.get_parser(doc.source_filename)
            parsed = await parser.parse(file_bytes, doc.source_filename)

            if not parsed.sections and not parsed.raw_text:
                raise AppError(ErrorCode.DOCUMENT_PARSE_FAILED, "解析结果为空")

            # 回写 content 供后续持久化查询
            await self._doc_repo.update_content(
                doc_id=doc.doc_id,
                content=parsed.raw_text,
            )
            return parsed
        except AppError:
            raise
        except Exception as e:
            raise AppError(
                ErrorCode.DOCUMENT_PARSE_FAILED,
                f"文档解析失败: {e}",
            )


async def purge_document_chunks(
    doc_id: str,
    store: VectorStorePort,
    keyword_store: KeywordSearchPort | None = None,
) -> None:
    """清理文档的向量和关键词索引。

    PG 端：documents 表 ON DELETE CASCADE 自动清理 chunks。
    ES 端：需显式按 doc_id 删除。
    """
    if keyword_store is not None:
        try:
            await keyword_store.delete_by_document(doc_id)
        except Exception as exc:
            logger.warning(
                "ES 清理文档 chunks 失败",
                extra={"doc_id": doc_id, "error": str(exc)},
            )
