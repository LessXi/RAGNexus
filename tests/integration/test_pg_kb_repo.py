"""Integration tests for PgKnowledgeBaseRepository with real PostgreSQL."""

import pytest

from ragnexus.adapters.knowledge_base.pg import PgKnowledgeBaseRepository
from ragnexus.domain.errors import ConflictError
from ragnexus.domain.models import KnowledgeBase

pytestmark = [pytest.mark.integration]

_KB_COUNTER = 0


def _unique_name(prefix: str = "kb_int") -> str:
    global _KB_COUNTER
    _KB_COUNTER += 1
    return f"{prefix}_{_KB_COUNTER}"


class TestPgKbRepoCreate:
    """PgKnowledgeBaseRepository.create() integration tests."""

    async def test_create_and_get(self, pg_pool):
        repo = PgKnowledgeBaseRepository(pg_pool)
        name = _unique_name()
        kb = await repo.create(name=name, name_key=name)

        assert isinstance(kb, KnowledgeBase)
        assert kb.id.startswith("kb_")
        assert kb.name == name

        fetched = await repo.get(kb.id)
        assert fetched is not None
        assert fetched.id == kb.id
        assert fetched.name == name

    async def test_get_not_found(self, pg_pool):
        repo = PgKnowledgeBaseRepository(pg_pool)
        result = await repo.get("kb_nonexistent_99999")
        assert result is None

    async def test_exists_true(self, pg_pool):
        repo = PgKnowledgeBaseRepository(pg_pool)
        name = _unique_name("exists")
        kb = await repo.create(name=name, name_key=name)
        assert await repo.exists(kb.id) is True

    async def test_exists_false(self, pg_pool):
        repo = PgKnowledgeBaseRepository(pg_pool)
        assert await repo.exists("kb_nonexistent_99999") is False

    async def test_duplicate_name_key(self, pg_pool):
        """Same name_key (lowercased) should raise ConflictError."""
        repo = PgKnowledgeBaseRepository(pg_pool)
        name = _unique_name("dup")
        await repo.create(name=name, name_key=name)
        with pytest.raises(ConflictError) as exc_info:
            await repo.create(name=name, name_key=name)
        assert exc_info.value.code == 1200
        assert exc_info.value.http_status == 409


class TestPgKbRepoDocExists:
    """PgKnowledgeBaseRepository.doc_exists() integration tests."""

    async def test_doc_exists_true(self, pg_pool):
        repo = PgKnowledgeBaseRepository(pg_pool)
        name = _unique_name("docexists")
        kb = await repo.create(name=name, name_key=name)
        doc_id = f"doc_{name}"

        # Insert document directly (documents table)
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO documents (doc_id, kb_id, filename, file_hash, file_size, content_type, chunk_count) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                doc_id,
                kb.id,
                "test.md",
                "abc123",
                100,
                "text/markdown",
                0,
            )

        assert await repo.doc_exists(doc_id) is True

    async def test_doc_exists_false(self, pg_pool):
        repo = PgKnowledgeBaseRepository(pg_pool)
        assert await repo.doc_exists("doc_nonexistent_99999") is False
