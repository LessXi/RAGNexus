"""Integration tests for PgRetrieveLogRepository with real PostgreSQL."""

import pytest

from adapters.retrieve_log.pg import PgRetrieveLogRepository

pytestmark = [pytest.mark.integration]

_TEST_COUNTER = 0


def _unique_tag() -> str:
    global _TEST_COUNTER
    _TEST_COUNTER += 1
    return f"int_{_TEST_COUNTER}"


class TestRetrieveLog:
    """PgRetrieveLogRepository.log() integration tests."""

    async def test_log_inserts_row(self, pg_pool):
        """Verify that log() inserts a row with correct values."""
        repo = PgRetrieveLogRepository(pg_pool)
        tag = _unique_tag()

        await repo.log(
            query=f"test query {tag}",
            kb_ids=[f"kb_{tag}_1", f"kb_{tag}_2"],
            top_k=5,
            hit_count=3,
            latency_ms=42,
        )

        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT query, kb_ids, top_k, hit_count, latency_ms "
                "FROM retrieve_logs WHERE query=$1",
                f"test query {tag}",
            )
            assert row is not None, "Row should exist in retrieve_logs"
            assert row["query"] == f"test query {tag}"
            assert row["kb_ids"] == [f"kb_{tag}_1", f"kb_{tag}_2"]
            assert row["top_k"] == 5
            assert row["hit_count"] == 3
            assert row["latency_ms"] == 42

    async def test_log_multiple_entries(self, pg_pool):
        """Multiple log entries should be stored independently."""
        repo = PgRetrieveLogRepository(pg_pool)

        for i in range(3):
            await repo.log(
                query=f"query_{i}",
                kb_ids=["kb_all"],
                top_k=10,
                hit_count=i,
                latency_ms=i * 10,
            )

        async with pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT query, hit_count, latency_ms FROM retrieve_logs "
                "WHERE query LIKE 'query_%' ORDER BY query",
            )
            assert len(rows) == 3
            assert [r["hit_count"] for r in rows] == [0, 1, 2]

    async def test_log_with_zero_hits(self, pg_pool):
        """Zero results is a valid log entry."""
        repo = PgRetrieveLogRepository(pg_pool)
        tag = _unique_tag()

        await repo.log(
            query=f"empty {tag}",
            kb_ids=["kb_miss"],
            top_k=5,
            hit_count=0,
            latency_ms=1,
        )

        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT hit_count FROM retrieve_logs WHERE query=$1",
                f"empty {tag}",
            )
            assert row["hit_count"] == 0

    async def test_log_auto_increment_id(self, pg_pool):
        """id (BIGSERIAL) should auto-increment."""
        repo = PgRetrieveLogRepository(pg_pool)
        tag1, tag2 = _unique_tag(), _unique_tag()

        await repo.log(query=f"first_{tag1}", kb_ids=["a"], top_k=1, hit_count=0, latency_ms=0)
        await repo.log(query=f"second_{tag2}", kb_ids=["b"], top_k=1, hit_count=0, latency_ms=0)

        async with pg_pool.acquire() as conn:
            id1 = await conn.fetchval(
                "SELECT id FROM retrieve_logs WHERE query=$1", f"first_{tag1}",
            )
            id2 = await conn.fetchval(
                "SELECT id FROM retrieve_logs WHERE query=$1", f"second_{tag2}",
            )
            assert isinstance(id1, int)
            assert isinstance(id2, int)
            assert id2 > id1  # auto-increment
