"""PgVectorStore — PostgreSQL + pgvector implementation of VectorStorePort."""

import json

import asyncpg
from pgvector.asyncpg import register_vector

from domain.errors import DuplicateDocumentError
from domain.models import Chunk, SearchHit


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
        dim: int,
        pool_min: int = 1,
        pool_max: int = 10,
        command_timeout: float = 30.0,
    ):
        self.dsn = dsn
        self.dim = dim
        self.pool_min = pool_min
        self.pool_max = pool_max
        self.command_timeout = command_timeout
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        """Create asyncpg connection pool with pgvector extension registered."""

        async def _init_conn(conn: asyncpg.Connection) -> None:
            await register_vector(conn)

        self.pool = await asyncpg.create_pool(
            self.dsn,
            min_size=self.pool_min,
            max_size=self.pool_max,
            command_timeout=self.command_timeout,
            init=_init_conn,
        )

    async def close(self) -> None:
        """Close the connection pool."""
        if self.pool is not None:
            await self.pool.close()

    async def upsert(self, kb_id: str, chunks: list[Chunk]) -> None:
        """Insert or reject chunks under a single transaction.

        Raises ``DuplicateDocumentError`` (1201) when any chunk with
        the same ``doc_id`` already exists in the store.
        """
        if not chunks:
            return
        doc_id = chunks[0].doc_id
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # 1. Deduplicate check (application-level guard + UNIQUE index)
                exists = await conn.fetchval(
                    "SELECT 1 FROM chunks WHERE doc_id = $1 LIMIT 1",
                    doc_id,
                )
                if exists:
                    raise DuplicateDocumentError(
                        f"doc_id={doc_id} 已存在",
                        errors=[
                            {
                                "field": "doc_id",
                                "reason": f"{doc_id} 已存在",
                            }
                        ],
                    )

                # 2. Insert document metadata row
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

                # 3. Batch insert chunks
                await conn.executemany(
                    """INSERT INTO chunks
                       (id, kb_id, doc_id, text, metadata, embedding)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    [
                        (
                            c.id,
                            c.kb_id,
                            c.doc_id,
                            c.text,
                            json.dumps(c.metadata),
                            c.vector,
                        )
                        for c in chunks
                    ],
                )

    async def search_by_vector(
        self,
        query_vector: list[float],
        top_k: int,
        kb_ids: list[str],
    ) -> list[SearchHit]:
        """Cosine-similarity search via pgvector ``<=>`` operator.

        Returns results sorted by descending score (``1 - cosine_distance``).
        """
        async with self.pool.acquire() as conn:
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
