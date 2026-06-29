"""PgRetrieveLogRepository — 检索日志适配器。

基于 asyncpg 实现 RetrieveLogPort（fire-and-forget 语义）。
"""

from datetime import datetime
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

    async def prune(self, before: datetime) -> int:
        """清理指定时间之前的旧日志，返回删除行数。"""
        result = await self.pool.execute(
            "DELETE FROM retrieve_logs WHERE created_at < $1", before
        )
        return int(result.split()[-1]) if result else 0
