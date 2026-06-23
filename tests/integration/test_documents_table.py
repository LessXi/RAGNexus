"""Integration tests for the documents table: FK cascade behavior."""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
]


class TestDocumentsTable:
    """Verify documents table FK constraint with CASCADE delete."""

    async def test_insert_document_success(self, pg_pool):
        """INSERT a document row and verify it can be read back."""
        kb_id = f"kb_doc_crud_{id(self)}"

        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO knowledge_bases (id, name, name_key) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                kb_id, "doc_crud_test", "doc_crud_test",
            )
            await conn.execute(
                "INSERT INTO documents (doc_id, kb_id, filename, file_hash, file_size, content_type, chunk_count) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                f"{kb_id}:doc1", kb_id, "readme.md", "sha256abc", 2048, "text/markdown", 3,
            )

            row = await conn.fetchrow(
                "SELECT doc_id, kb_id, filename, file_size, content_type, chunk_count "
                "FROM documents WHERE doc_id=$1",
                f"{kb_id}:doc1",
            )
            assert row is not None
            assert row["doc_id"] == f"{kb_id}:doc1"
            assert row["kb_id"] == kb_id
            assert row["filename"] == "readme.md"
            assert row["file_size"] == 2048
            assert row["chunk_count"] == 3

    async def test_fk_cascade_on_kb_delete(self, pg_pool):
        """Deleting a KB should CASCADE to its documents."""
        kb_id = f"kb_cascade_{id(self)}"

        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO knowledge_bases (id, name, name_key) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                kb_id, "cascade_test", "cascade_test",
            )
            await conn.execute(
                "INSERT INTO documents (doc_id, kb_id, filename, file_hash, file_size, content_type, chunk_count) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                f"{kb_id}:doc_c", kb_id, "cascade.md", "def456", 512, "text/markdown", 1,
            )

            # Delete KB — documents should cascade
            await conn.execute("DELETE FROM knowledge_bases WHERE id=$1", kb_id)

            orphan = await conn.fetchrow(
                "SELECT 1 FROM documents WHERE doc_id=$1",
                f"{kb_id}:doc_c",
            )
            assert orphan is None, "Document should be cascade-deleted with KB"

    async def test_fk_violation_no_parent_kb(self, pg_pool):
        """INSERT with a non-existent kb_id should raise FK violation."""
        async with pg_pool.acquire() as conn:
            with pytest.raises(Exception) as exc_info:
                await conn.execute(
                    "INSERT INTO documents (doc_id, kb_id, filename, file_hash, file_size, content_type, chunk_count) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    "doc_fk_bad", "kb_does_not_exist_9999", "bad.md", "xxx", 0, "text/plain", 0,
                )
            # asyncpg raises ForeignKeyViolation (subclass of PostgresError)
            assert "violates foreign key" in str(exc_info.value).lower()

    async def test_multiple_documents_per_kb(self, pg_pool):
        """A KB can hold multiple documents."""
        kb_id = f"kb_multi_doc_{id(self)}"

        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO knowledge_bases (id, name, name_key) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                kb_id, "multi_doc_test", "multi_doc_test",
            )

            for i in range(3):
                await conn.execute(
                    "INSERT INTO documents (doc_id, kb_id, filename, file_hash, file_size, content_type, chunk_count) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    f"{kb_id}:doc{i}", kb_id, f"file{i}.md", f"hash{i}", 100, "text/markdown", 0,
                )

            count = await conn.fetchval(
                "SELECT COUNT(*) FROM documents WHERE kb_id=$1", kb_id,
            )
            assert count == 3
