"""UploadDocumentUseCase — orchestrates file validation, parsing, chunking, embedding, and storage.

The full pipeline:
1. File size check (≤ max_file_size, default 10MB)
2. File extension check (.md / .txt only)
3. KB existence check
4. doc_id = SHA256(file_content)[:16] with "doc_" prefix
5. Dedup check via kb_repo.doc_exists()
6. Parse (ParserPort)
7. Chunk (injected chunker function)
8. Embed (EmbedderPort, batch/concurrency handled internally)
9. Construct Chunk list with common_meta
10. Transactional upsert (store.upsert)
Returns UploadResult.
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
    """Upload a document to a knowledge base — full synchronous pipeline."""

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
        """Run the full upload pipeline.

        Raises:
            AppError(ErrorCode.FILE_TOO_LARGE): file exceeds max_file_size.
            AppError(ErrorCode.UNSUPPORTED_FORMAT): extension not in allowed_exts.
            AppError(ErrorCode.NOT_FOUND): kb_id does not exist.
            AppError(ErrorCode.RESOURCE_EXISTS): doc_id already exists (detected before parse).
            AppError(ErrorCode.FILE_EMPTY): file has no parseable content.
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
        parsed = self._parser.parse(file_content, filename)
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

        return UploadResult(doc_id=doc_id, kb_id=kb_id, chunks=chunks)
