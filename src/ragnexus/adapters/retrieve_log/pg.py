"""PgRetrieveLogRepository — outbound adapter for retrieve logging.

Implements RetrieveLogPort over asyncpg (fire-and-forget semantics).
"""

import asyncpg


class PgRetrieveLogRepository:
    """Postgres (asyncpg) adapter for writing retrieve log entries."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def log(
        self,
        *,
        query: str,
        kb_ids: list[str],
        top_k: int,
        hit_count: int,
        latency_ms: int,
    ) -> None:
        """Insert a retrieve_log row (fire-and-forget)."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO retrieve_logs (kb_ids, query, top_k, hit_count, latency_ms)
                   VALUES ($1, $2, $3, $4, $5)""",
                kb_ids, query, top_k, hit_count, latency_ms,
            )
