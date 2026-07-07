"""Tests for PgRetrieveLogRepository — log() with 11 columns (6 required + 5 optional)."""

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
        )

        mock_pool.acquire.assert_called_once()
        conn = mock_pool.acquire.return_value._conn
        conn.execute.assert_awaited_once()

        sql = conn.execute.await_args[0][0]
        assert sql.startswith("INSERT INTO retrieve_logs")
        # 验证所有 11 列都在 INSERT 中
        for col in (
            "kb_ids",
            "query",
            "top_k",
            "hit_count",
            "latency_ms",
            "log_id",
            "tenant_id",
            "trace_id",
            "profile",
            "search_query",
            "effective_query",
        ):
            assert col in sql, f"Column {col} missing from INSERT"

        args = conn.execute.await_args[0][1:]
        assert len(args) == 11
        # 前 6 个参数来自调用，后 5 个为默认空值
        assert args[5] == "log-abc-123"  # log_id
        assert args[6] == ""  # tenant_id (default)
        assert args[7] == ""  # trace_id (default)
        assert args[8] == ""  # profile (default)
        assert args[9] == ""  # search_query (default)
        assert args[10] == ""  # effective_query (default)

    @pytest.mark.asyncio
    async def test_log_with_all_fields(self, repo, mock_pool):
        """log() with all 11 fields explicitly set."""
        await repo.log(
            query="test",
            kb_ids=["kb_1"],
            top_k=5,
            hit_count=3,
            latency_ms=42,
            log_id="log-1",
            tenant_id="tenant-x",
            trace_id="trace-y",
            profile="balanced",
            search_query="expanded",
            effective_query="rewritten",
        )

        conn = mock_pool.acquire.return_value._conn
        args = conn.execute.await_args[0][1:]
        assert args[5] == "log-1"
        assert args[6] == "tenant-x"
        assert args[7] == "trace-y"
        assert args[8] == "balanced"
        assert args[9] == "expanded"
        assert args[10] == "rewritten"
