"""UploadDocumentUseCase — 编排文件校验、解析、分块、嵌入和存储。

完整流水线：
1. 文件大小检查（≤ max_file_size，默认 10MB）
2. 文件扩展名检查（仅 .md / .txt）
3. KB 存在性检查
4. doc_id = SHA256(file_content)[:16] 加 "doc_" 前缀
5. 去重检查 via kb_repo.doc_exists()
6. 解析（ParserPort）
7. 分块（注入的 chunker 函数）
8. 嵌入（EmbedderPort，批次/并发内部处理）
9. 构造带 common_meta 的 Chunk 列表
10. 事务性 upsert（store.upsert）
返回 UploadResult。
"""

import hashlib
from collections.abc import Callable

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.core.logger import logger
from ragnexus.domain.models import Chunk, UploadResult
from ragnexus.domain.ports import (
    EmbedderPort,
    KnowledgeBasePort,
    ParserPort,
    VectorStorePort,
)


class UploadDocumentUseCase:
    """上传文档到知识库 — 完整同步流水线。"""

    def __init__(
        self,
        kb_repo: KnowledgeBasePort,
        parser: ParserPort,
        embedder: EmbedderPort,
        chunker: Callable[..., list[dict]],
        store: VectorStorePort,
        max_file_size: int = 10 * 1024 * 1024,
        allowed_exts: tuple[str, ...] = (".md", ".txt"),
        chunk_max_chars: int = 1500,
        chunk_overlap: int = 50,
    ) -> None:
        self._kb_repo = kb_repo
        self._parser = parser
        self._embedder = embedder
        self._chunker = chunker
        self._store = store
        self._max_file_size = max_file_size
        self._allowed_exts = allowed_exts
        self._chunk_max_chars = chunk_max_chars
        self._chunk_overlap = chunk_overlap

    async def execute(
        self,
        kb_id: str,
        file_content: bytes,
        filename: str,
        content_type: str,
    ) -> UploadResult:
        """运行完整上传流水线。

        返回 UploadResult（含 chunks 供测试断言；router 应使用 chunk_count 字段）。

        Raises:
            AppError(ErrorCode.FILE_TOO_LARGE): 文件超过大小限制。
            AppError(ErrorCode.UNSUPPORTED_FORMAT): 不支持的文件扩展名。
            AppError(ErrorCode.NOT_FOUND): kb_id 不存在。
            AppError(ErrorCode.RESOURCE_EXISTS): doc_id 已存在（解析前检测）。
            AppError(ErrorCode.FILE_EMPTY): 文件无可解析内容。
        """
        # 1. File size check
        if len(file_content) > self._max_file_size:
            raise AppError(
                ErrorCode.FILE_TOO_LARGE,
                "文件过大",
                errors=[
                    {
                        "field": "file",
                        "reason": f"文件大小超过 {self._max_file_size} 字节限制",
                    }
                ],
            )

        # 2. File extension check
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in self._allowed_exts:
            raise AppError(
                ErrorCode.UNSUPPORTED_FORMAT,
                f"不支持的文件类型: {ext}",
                errors=[
                    {
                        "field": "filename",
                        "reason": f"仅支持 {', '.join(self._allowed_exts)} 格式",
                    }
                ],
            )

        # 3. KB existence check
        if not await self._kb_repo.exists(kb_id):
            raise AppError(
                ErrorCode.NOT_FOUND,
                "知识库不存在",
                errors=[{"field": "kb_id", "reason": f"{kb_id} 不存在"}],
            )

        # 4. Compute doc_id + file_hash
        file_hash = hashlib.sha256(file_content).hexdigest()
        doc_id = "doc_" + file_hash[:16]

        # 5. Dedup check (before parsing — avoid wasted work)
        if await self._kb_repo.doc_exists(doc_id):
            raise AppError(
                ErrorCode.RESOURCE_EXISTS,
                "文档已存在",
                errors=[{"field": "doc_id", "reason": f"{doc_id} 已存在"}],
            )

        # 6. Parse
        parsed = await self._parser.parse(file_content, filename)
        if not parsed.sections and not parsed.raw_text:
            raise AppError(
                ErrorCode.FILE_EMPTY,
                "文件为空",
                errors=[{"field": "file", "reason": "文件内容为空"}],
            )

        # 7. Chunk
        chunk_dicts = self._chunker(
            parsed, max_chars=self._chunk_max_chars, overlap=self._chunk_overlap
        )
        if not chunk_dicts:
            raise AppError(
                ErrorCode.FILE_EMPTY,
                "文件为空",
                errors=[{"field": "file", "reason": "文件内容为空"}],
            )

        # Extract texts for embedding
        texts = [cd["text"] for cd in chunk_dicts]

        # 8. Embed
        vectors = await self._embedder.embed(texts)

        # 9. Construct Chunk list
        common_meta: dict = {
            "filename": filename,
            "file_hash": file_hash,
            "file_size": len(file_content),
            "content_type": content_type,
        }
        chunks = [
            Chunk(
                id=f"{doc_id}:{i}",
                kb_id=kb_id,
                doc_id=doc_id,
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

        # 10. Transactional write (all-or-nothing)
        await self._store.upsert(kb_id, chunks)

        # BIZ_EVENT: 文档上传成功（用户可感知结果）
        logger.info(
            "",
            extra={
                "event_type": "BIZ_EVENT",
                "event": "document_uploaded",
                "kb_id": kb_id,
                "doc_id": doc_id,
                "chunks": len(chunks),
            },
        )

        return UploadResult(
            doc_id=doc_id, kb_id=kb_id, chunks=chunks, chunk_count=len(chunks)
        )
