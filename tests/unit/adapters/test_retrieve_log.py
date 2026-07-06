"""Tests for PgRetrieveLogRepository — TDD RED phase."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ragnexus.adapters.retrieve_log.pg import PgRetrieveLogRepository


class _CtxAcquirer:
    """Minimal async context manager for mocking asyncpg.Pool.acquire()."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


@pytest.fixture
def mock_pool():
    """Return a MagicMock for asyncpg.Pool wired for async context manager."""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value = _CtxAcquirer(conn)
    return pool


@pytest.fixture
def repo(mock_pool):
    """Return a PgRetrieveLogRepository with a mocked pool."""
    return PgRetrieveLogRepository(pool=mock_pool)


class TestLog:
    """Tests for PgRetrieveLogRepository.log()."""

    @pytest.mark.asyncio
    async def test_log_inserts_row(self, repo, mock_pool):
        """log() should acquire a connection and execute an INSERT with all 11 columns."""
        await repo.log(
            query="test query",
            kb_ids=["kb_1", "kb_2"],
            top_k=5,
            hit_count=3,
            latency_ms=42,
            log_id="log-abc-123",
            tenant_id="tenant-xyz",
            trace_id="trace-456",
            profile="balanced",
            search_query="expanded query",
            effective_query="rewritten query",
        )

        mock_pool.acquire.assert_called_once()
        conn = mock_pool.acquire.return_value._conn
        conn.execute.assert_awaited_once()

        sql = conn.execute.await_args[0][0]
        assert sql.startswith("INSERT INTO retrieve_logs")
        assert "log_id" in sql
        assert "tenant_id" in sql
        assert "trace_id" in sql
        assert "profile" in sql
        assert "search_query" in sql
        assert "effective_query" in sql

        args = conn.execute.await_args[0][1:]
        assert len(args) == 11
        assert args[5] == "log-abc-123"
        assert args[6] == "tenant-xyz"
        assert args[7] == "trace-456"
        assert args[8] == "balanced"
        assert args[9] == "expanded query"
        assert args[10] == "rewritten query"
