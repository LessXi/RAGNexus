"""PgDocumentRepository — 文档 CRUD 适配器。"""

from datetime import UTC, datetime

import asyncpg

from ragnexus.domain.models import DocStatus, Document


class PgDocumentRepository:
    """Postgres (asyncpg) 文档 CRUD 适配器。"""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def get(self, doc_id: str) -> Document | None:
        row = await self.pool.fetchrow(
            "SELECT doc_id, kb_id, filename, file_hash, file_size, "
            "content_type, content, source_file_path, source_filename, "
            "status, chunk_count, "
            "error_message, uploaded_at, updated_at "
            "FROM documents WHERE doc_id = $1",
            doc_id,
        )
        if row is None:
            return None
        return Document(
            doc_id=row["doc_id"],
            kb_id=row["kb_id"],
            filename=row["filename"],
            file_hash=row["file_hash"],
            file_size=row["file_size"],
            content_type=row["content_type"],
            content=row["content"] or "",
            status=DocStatus(row["status"]),
            chunk_count=row["chunk_count"] or 0,
            source_file_path=row["source_file_path"],
            source_filename=row["source_filename"],
            error_message=row["error_message"],
            uploaded_at=row["uploaded_at"],
            updated_at=row["updated_at"],
        )

    async def create(
        self,
        *,
        doc_id,
        kb_id,
        filename,
        file_hash,
        file_size,
        content_type,
        content,
        source_file_path=None,
        source_filename=None,
    ) -> Document:
        now = datetime.now(UTC)
        await self.pool.execute(
            "INSERT INTO documents (doc_id, kb_id, filename, file_hash, "
            "file_size, content_type, content, source_file_path, source_filename, "
            "status, chunk_count, uploaded_at, updated_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
            doc_id,
            kb_id,
            filename,
            file_hash,
            file_size,
            content_type,
            content,
            source_file_path,
            source_filename,
            DocStatus.PROCESSING.value,
            0,  # chunk_count — 索引完成后由 IndexingService 更新
            now,
            now,
        )
        return Document(
            doc_id=doc_id,
            kb_id=kb_id,
            filename=filename,
            file_hash=file_hash,
            file_size=file_size,
            content_type=content_type,
            content=content,
            source_file_path=source_file_path,
            source_filename=source_filename,
            status=DocStatus.PROCESSING,
            uploaded_at=now,
            updated_at=now,
        )

    async def update_status(
        self, doc_id, *, status, error_message=None, chunk_count=None
    ) -> None:
        updates = ["status = $1", "updated_at = $2"]
        params: list = [status.value, datetime.now(UTC)]
        idx = 3
        if error_message is not None:
            updates.append(f"error_message = ${idx}")
            params.append(error_message)
            idx += 1
        if chunk_count is not None:
            updates.append(f"chunk_count = ${idx}")
            params.append(chunk_count)
            idx += 1
        params.append(doc_id)
        await self.pool.execute(
            f"UPDATE documents SET {', '.join(updates)} WHERE doc_id = ${idx}",
            *params,
        )

    async def delete(self, doc_id: str) -> None:
        await self.pool.execute("DELETE FROM documents WHERE doc_id = $1", doc_id)

    async def delete_by_kb(self, kb_id: str) -> None:
        await self.pool.execute("DELETE FROM documents WHERE kb_id = $1", kb_id)

    async def has_processing(self, kb_id: str) -> bool:
        result = await self.pool.fetchval(
            "SELECT 1 FROM documents WHERE kb_id = $1 AND status = $2 LIMIT 1",
            kb_id,
            DocStatus.PROCESSING.value,
        )
        return result is not None

    async def get_by_kb(self, kb_id: str) -> list[Document]:
        rows = await self.pool.fetch(
            "SELECT doc_id, kb_id, filename, file_hash, file_size, "
            "content_type, content, source_file_path, source_filename, "
            "status, chunk_count, "
            "error_message, uploaded_at, updated_at "
            "FROM documents WHERE kb_id = $1 ORDER BY uploaded_at DESC",
            kb_id,
        )
        return [
            Document(
                doc_id=r["doc_id"],
                kb_id=r["kb_id"],
                filename=r["filename"],
                file_hash=r["file_hash"],
                file_size=r["file_size"],
                content_type=r["content_type"],
                content=r["content"] or "",
                status=DocStatus(r["status"]),
                chunk_count=r["chunk_count"] or 0,
                source_file_path=r["source_file_path"],
                source_filename=r["source_filename"],
                error_message=r["error_message"],
                uploaded_at=r["uploaded_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    async def update_content(self, doc_id: str, content: str) -> None:
        """更新文档 content 字段 — 供 _prepare_content 延迟解析后回写。"""
        await self.pool.execute(
            "UPDATE documents SET content = $1, updated_at = $2 WHERE doc_id = $3",
            content,
            datetime.now(UTC),
            doc_id,
        )
