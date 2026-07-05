"""UploadDocumentUseCase — 编排文件校验、持久化和异步索引触发。

流水线（同步部分）：
1. 文件大小检查（≤ max_file_size，默认 10MB）
2. 文件扩展名检查（仅 .md / .txt）
3. KB 存在性检查
4. doc_id = SHA256(file_content)[:16] 加 "doc_" 前缀
5. 去重检查 via kb_repo.doc_exists()
6. 解码文件内容，创建 Document 记录（状态 PROCESSING）
7. 提交 Celery 异步索引任务（解析→分块→嵌入→双写）
返回 UploadResult（status=PROCESSING）。

实际索引工作由 Worker 进程通过 IndexingService 异步完成。
"""

import hashlib
from collections.abc import Callable
from typing import TYPE_CHECKING

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.core.logger import logger
from ragnexus.domain.models import Chunk, DocStatus, UploadResult
from ragnexus.domain.ports import (
    DocumentPort,
    EmbedderPort,
    KnowledgeBasePort,
    KeywordSearchPort,
    ParserPort,
    VectorStorePort,
)

if TYPE_CHECKING:
    from ragnexus.adapters.vector_store.pgvector import PgVectorStore


class UploadDocumentUseCase:
    """上传文档到知识库 — 同步校验 + 异步索引触发。"""

    def __init__(
        self,
        kb_repo: KnowledgeBasePort,
        doc_repo: DocumentPort,
        parser: ParserPort,
        embedder: EmbedderPort,
        chunker: Callable[..., list[dict]],
        store: VectorStorePort,
        max_file_size: int = 10 * 1024 * 1024,
        allowed_exts: tuple[str, ...] = (".md", ".txt"),
        chunk_max_chars: int = 1500,
        chunk_overlap: int = 50,
        keyword_store: KeywordSearchPort | None = None,
        es_enabled: bool = False,
    ) -> None:
        self._kb_repo = kb_repo
        self._doc_repo = doc_repo
        self._parser = parser
        self._embedder = embedder
        self._chunker = chunker
        self._store = store
        self._pg_store: PgVectorStore = store  # type: ignore[assignment]
        self._max_file_size = max_file_size
        self._allowed_exts = allowed_exts
        self._chunk_max_chars = chunk_max_chars
        self._chunk_overlap = chunk_overlap
        self._keyword_store = keyword_store
        self._es_enabled = es_enabled

    async def execute(
        self,
        kb_id: str,
        tenant_id: str,
        file_content: bytes,
        filename: str,
        content_type: str,
    ) -> UploadResult:
        """运行同步校验流水线，提交异步索引任务。

        返回 UploadResult（status=PROCESSING，chunks 为空，chunk_count=0）。

        Raises:
            AppError(ErrorCode.FILE_TOO_LARGE): 文件超过大小限制。
            AppError(ErrorCode.UNSUPPORTED_FORMAT): 不支持的文件扩展名。
            AppError(ErrorCode.NOT_FOUND): kb_id 不存在。
            AppError(ErrorCode.FORBIDDEN): kb_id 不属于当前租户。
            AppError(ErrorCode.RESOURCE_EXISTS): doc_id 已存在。
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

        # 3. KB existence + tenant ownership check
        kb = await self._kb_repo.get(kb_id)
        if kb is None:
            raise AppError(
                ErrorCode.NOT_FOUND,
                "知识库不存在",
                errors=[{"field": "kb_id", "reason": f"{kb_id} 不存在"}],
            )
        if kb.tenant_id != tenant_id:
            raise AppError(
                ErrorCode.FORBIDDEN,
                f"知识库 {kb_id} 不属于当前租户",
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

        # 6. 解码文件内容
        text_content = file_content.decode("utf-8", errors="replace")

        # 7. 创建 Document 记录（状态 PROCESSING）
        doc = await self._doc_repo.create(
            doc_id=doc_id,
            kb_id=kb_id,
            filename=filename,
            file_hash=file_hash,
            file_size=len(file_content),
            content_type=content_type,
            content=text_content,
        )

        # 8. 提交异步索引任务
        from ragnexus.tasks.indexing import index_document_task

        index_document_task.delay(doc_id)

        # BIZ_EVENT: 文档上传成功（异步处理中）
        logger.info(
            "",
            extra={
                "event_type": "BIZ_EVENT",
                "event": "document_uploaded",
                "kb_id": kb_id,
                "doc_id": doc_id,
            },
        )

        return UploadResult(
            doc_id=doc_id,
            kb_id=kb_id,
            status=DocStatus.PROCESSING,
            chunks=[],
            chunk_count=0,
        )
