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
        """log() should acquire a connection and execute an INSERT."""
        await repo.log(
            query="test query",
            kb_ids=["kb_1", "kb_2"],
            top_k=5,
            hit_count=3,
            latency_ms=42,
        )

        # acquire() is a sync call returning a context manager
        mock_pool.acquire.assert_called_once()

        # Get the connection that was acquired via async context manager
        conn = mock_pool.acquire.return_value._conn
        conn.execute.assert_awaited_once()

        # Verify the SQL is an INSERT into retrieve_logs
        sql = conn.execute.await_args[0][0]
        assert sql.startswith("INSERT INTO retrieve_logs")
