"""Tests for PgKnowledgeBaseRepository — TDD RED phase."""

from datetime import datetime
from unittest.mock import AsyncMock

import asyncpg
import pytest

from ragnexus.adapters.knowledge_base.pg import PgKnowledgeBaseRepository
from ragnexus.core.errors import AppError
from ragnexus.domain.models import KnowledgeBase


@pytest.fixture
def mock_pool():
    """Return an AsyncMock for asyncpg.Pool."""
    return AsyncMock()


@pytest.fixture
def repo(mock_pool):
    """Return a PgKnowledgeBaseRepository with a mocked pool."""
    return PgKnowledgeBaseRepository(pool=mock_pool)


class TestCreate:
    """Tests for PgKnowledgeBaseRepository.create()."""

    @pytest.mark.asyncio
    async def test_create_success(self, repo, mock_pool):
        """create() should INSERT a KB and return a KnowledgeBase domain model."""
        now = datetime.now()
        mock_pool.fetchrow.return_value = {
            "id": "kb_abc123",
            "name": "My KB",
            "created_at": now,
        }

        result = await repo.create(name="My KB", name_key="my kb")

        assert isinstance(result, KnowledgeBase)
        assert result.name == "My KB"
        assert result.created_at == now
        assert result.id.startswith("kb_")
        mock_pool.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_duplicate_name(self, repo, mock_pool):
        """create() should raise ConflictError when name_key violates UNIQUE."""
        mock_pool.fetchrow.side_effect = asyncpg.UniqueViolationError("duplicate key value")

        with pytest.raises(AppError) as exc_info:
            await repo.create(name="Dup", name_key="dup")

        assert exc_info.value.errors[0]["field"] == "name"


class TestGet:
    """Tests for PgKnowledgeBaseRepository.get()."""

    @pytest.mark.asyncio
    async def test_get_found(self, repo, mock_pool):
        """get() should return KnowledgeBase when the row exists."""
        now = datetime.now()
        mock_pool.fetchrow.return_value = {
            "id": "kb_abc",
            "name": "Test",
            "created_at": now,
        }

        result = await repo.get("kb_abc")

        assert isinstance(result, KnowledgeBase)
        assert result.id == "kb_abc"
        assert result.name == "Test"
        assert result.created_at == now
        mock_pool.fetchrow.assert_awaited_once_with(
            "SELECT id, name, created_at FROM knowledge_bases WHERE id=$1",
            "kb_abc",
        )

    @pytest.mark.asyncio
    async def test_get_not_found(self, repo, mock_pool):
        """get() should return None when no row matches."""
        mock_pool.fetchrow.return_value = None

        result = await repo.get("kb_nonexistent")

        assert result is None


class TestExists:
    """Tests for PgKnowledgeBaseRepository.exists()."""

    @pytest.mark.asyncio
    async def test_exists_true(self, repo, mock_pool):
        """exists() should return True when KB exists."""
        mock_pool.fetchval.return_value = 1

        result = await repo.exists("kb_abc")

        assert result is True
        mock_pool.fetchval.assert_awaited_once_with(
            "SELECT 1 FROM knowledge_bases WHERE id=$1",
            "kb_abc",
        )

    @pytest.mark.asyncio
    async def test_exists_false(self, repo, mock_pool):
        """exists() should return False when KB does not exist."""
        mock_pool.fetchval.return_value = None

        result = await repo.exists("kb_nonexistent")

        assert result is False


class TestDocExists:
    """Tests for PgKnowledgeBaseRepository.doc_exists()."""

    @pytest.mark.asyncio
    async def test_doc_exists_true(self, repo, mock_pool):
        """doc_exists() should return True when the doc exists in the documents table."""
        mock_pool.fetchval.return_value = 1

        result = await repo.doc_exists("doc_123")

        assert result is True
        mock_pool.fetchval.assert_awaited_once_with(
            "SELECT 1 FROM documents WHERE doc_id=$1",
            "doc_123",
        )

    @pytest.mark.asyncio
    async def test_doc_exists_false(self, repo, mock_pool):
        """doc_exists() should return False when no doc matches."""
        mock_pool.fetchval.return_value = None

        result = await repo.doc_exists("doc_nonexistent")

        assert result is False
