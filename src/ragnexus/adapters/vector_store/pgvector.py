"""PgVectorStore — 基于 PostgreSQL + pgvector 的 VectorStorePort 实现。"""

import json
from typing import Any

import asyncpg
from pgvector.asyncpg import register_vector

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import Chunk, SearchHit


class PgVectorStore:
    """向量存储 + 检索，基于 pgvector。

    Usage::

        store = PgVectorStore(dsn="postgresql://...", dim=1024)
        await store.connect()
        try:
            await store.upsert(kb_id, chunks)
            hits = await store.search_by_vector(query_vector, top_k, kb_ids)
        finally:
            await store.close()
    """

    def __init__(
        self,
        dsn: str,
        pool_min: int = 1,
        pool_max: int = 10,
        command_timeout: float = 30.0,
    ):
        self.dsn = dsn
        self.pool_min = pool_min
        self.pool_max = pool_max
        self.command_timeout = command_timeout
        self.pool: asyncpg.Pool | Any = None
        self._owns_pool: bool = False

    async def connect(self, external_pool: Any = None) -> None:
        """创建连接池或接受外部注入的 pool。

        若 external_pool 为 None，内部创建 asyncpg.Pool（保持向后兼容）；
        否则直接使用传入的 pool（例如 LoggedPool 包装后的实例），不负责关闭。
        """
        if external_pool is not None:
            self.pool = external_pool
            self._owns_pool = False
            return

        async def _init_conn(conn: asyncpg.Connection) -> None:
            await register_vector(conn)

        self.pool = await asyncpg.create_pool(
            self.dsn,
            min_size=self.pool_min,
            max_size=self.pool_max,
            command_timeout=self.command_timeout,
            init=_init_conn,
        )
        self._owns_pool = True

    async def close(self) -> None:
        """关闭连接池 — 仅当自己持有时。"""
        if self._owns_pool and self.pool is not None:
            await self.pool.close()

    async def acquire_connection(self) -> asyncpg.Connection:
        """从连接池获取一个连接。

        Returns:
            asyncpg.Connection: 从池中取出的原始连接。
        """
        assert self.pool is not None, "调用 connect() 先"
        return await self.pool.acquire()

    async def _upsert_in_transaction(
        self, conn: asyncpg.Connection, kb_id: str, chunks: list[Chunk]
    ) -> None:
        """在已有连接上开启事务并执行 upsert 核心逻辑。

        不提交事务 — 由调用方决定 commit 或 rollback。

        当存在相同 ``doc_id`` 的 chunk 时抛出 ``AppError(ErrorCode.RESOURCE_EXISTS)``。
        """
        if not chunks:
            return
        doc_id = chunks[0].doc_id

        # 注册 pgvector 编码器（external_pool 场景必需）
        await register_vector(conn)

        # 开启事务（在重复检查前开启，确保异常时调用方可 ROLLBACK）
        await conn.execute("BEGIN")

        # 1. Deduplicate check（应用层守卫 + UNIQUE 索引）
        exists = await conn.fetchval(
            "SELECT 1 FROM chunks WHERE doc_id = $1 LIMIT 1",
            doc_id,
        )
        if exists:
            raise AppError(
                ErrorCode.RESOURCE_EXISTS,
                f"doc_id={doc_id} 已存在",
                errors=[
                    {
                        "field": "doc_id",
                        "reason": f"{doc_id} 已存在",
                    }
                ],
            )

        try:
            # 2. 插入文档元数据行
            first = chunks[0]
            await conn.execute(
                """INSERT INTO documents
                       (doc_id, kb_id, filename, file_hash,
                        file_size, content_type, chunk_count)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)
                       ON CONFLICT (doc_id) DO NOTHING""",
                first.doc_id,
                first.kb_id,
                first.metadata.get("filename", ""),
                first.metadata.get("file_hash", ""),
                first.metadata.get("file_size", 0),
                first.metadata.get("content_type"),
                len(chunks),
            )

            # 3. 逐条插入 chunks
            # 使用逐条 execute 而非 executemany：executemany 的二进制协议
            # 无法正确序列化 list[float] → pgvector 类型，而单条 execute 可以
            for c in chunks:
                await conn.execute(
                    """INSERT INTO chunks
                           (id, kb_id, doc_id, text, metadata, embedding)
                           VALUES ($1, $2, $3, $4, $5, $6)""",
                    c.id,
                    c.kb_id,
                    c.doc_id,
                    c.text,
                    json.dumps(c.metadata),
                    c.vector,
                )
        except asyncpg.UniqueViolationError as e:
            raise AppError(
                ErrorCode.RESOURCE_EXISTS,
                f"doc_id={doc_id} 已存在",
                errors=[
                    {
                        "field": "doc_id",
                        "reason": f"{doc_id} 已存在",
                    }
                ],
            ) from e

    async def upsert(self, kb_id: str, chunks: list[Chunk]) -> None:
        """在单事务中插入或更新 chunk（便捷方法）。

        内部管理连接获取/释放和事务提交/回滚。
        当存在相同 ``doc_id`` 的 chunk 时抛出 ``AppError(ErrorCode.RESOURCE_EXISTS)``。
        """
        if not chunks:
            return
        conn = await self.acquire_connection()
        try:
            await self._upsert_in_transaction(conn, kb_id, chunks)
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise
        finally:
            await self.pool.release(conn)

    async def search_by_vector(
        self,
        query_vector: list[float],
        top_k: int,
        kb_ids: list[str],
    ) -> list[SearchHit]:
        """通过 pgvector ``<=>`` 运算符进行余弦相似度搜索。

        按分数降序返回结果（``1 - cosine_distance``）。
        """
        assert self.pool is not None, "call connect() first"
        async with self.pool.acquire() as conn:
            await register_vector(conn)  # 注册 pgvector 编码器
            rows = await conn.fetch(
                """SELECT id, kb_id, doc_id, text, metadata,
                          1 - (embedding <=> $1) AS score
                   FROM chunks
                   WHERE kb_id = ANY($2)
                   ORDER BY embedding <=> $1
                   LIMIT $3""",
                query_vector,
                kb_ids,
                top_k,
            )
        return [
            SearchHit(
                chunk_id=r["id"],
                kb_id=r["kb_id"],
                doc_id=r["doc_id"],
                score=float(r["score"]),
                text=r["text"],
                metadata=json.loads(r["metadata"]),
            )
            for r in rows
        ]
