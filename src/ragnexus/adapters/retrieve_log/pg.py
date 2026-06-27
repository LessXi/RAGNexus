"""PgRetrieveLogRepository — 检索日志适配器。

基于 asyncpg 实现 RetrieveLogPort（fire-and-forget 语义）。
"""

import asyncpg


class PgRetrieveLogRepository:
    """Postgres (asyncpg) 检索日志写入适配器。"""

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
        """插入一条检索日志（fire-and-forget）。"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO retrieve_logs (kb_ids, query, top_k, hit_count, latency_ms)
                   VALUES ($1, $2, $3, $4, $5)""",
                kb_ids,
                query,
                top_k,
                hit_count,
                latency_ms,
            )
