"""Integration tests for PgVectorStore with real pgvector.

These tests require Docker with PostgreSQL + pgvector (test-db on port 5433).
They test real vector operations: upsert chunks and cosine-similarity search.
"""

import pytest
import pytest_asyncio

from adapters.vector_store.pgvector import PgVectorStore
from domain.errors import DuplicateDocumentError
from domain.models import Chunk, SearchHit

pytestmark = [pytest.mark.integration]

TEST_DIM = 1024
TEST_DSN = "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test"


def _make_vec(*seed_vals: float) -> list[float]:
    """Create a TEST_DIM-dim vector, padding with zeros after seed values."""
    vec = [0.0] * TEST_DIM
    for i, v in enumerate(seed_vals):
        vec[i] = float(v)
    return vec


class TestPgVectorStore:
    """PgVectorStore upsert + search integration tests."""

    @pytest_asyncio.fixture
    async def store(self):
        """Create a PgVectorStore connected to test-db."""
        s = PgVectorStore(dsn=TEST_DSN, dim=TEST_DIM, pool_min=1, pool_max=2)
        await s.connect()
        yield s
        await s.close()

    async def _ensure_kb(self, kb_id: str, pool) -> None:
        """Ensure a KB row exists (vector ops depend on FK constraint)."""
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO knowledge_bases (id, name, name_key) "
                "VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
                kb_id, kb_id, kb_id,
            )

    async def test_upsert_new_doc(self, store, pg_pool):
        """Upsert chunks for a new document succeeds."""
        kb_id = f"kb_up_new_{id(self)}"
        doc_id = f"doc_up_new_{id(self)}"
        await self._ensure_kb(kb_id, pg_pool)

        chunks = [
            Chunk(
                id=f"{doc_id}:0", kb_id=kb_id, doc_id=doc_id,
                text="hello world", vector=_make_vec(0.1, 0.2, 0.3),
                metadata={"filename": "test.md", "chunk_index": 0},
            ),
            Chunk(
                id=f"{doc_id}:1", kb_id=kb_id, doc_id=doc_id,
                text="goodbye world", vector=_make_vec(0.9, 0.8, 0.7),
                metadata={"filename": "test.md", "chunk_index": 1},
            ),
        ]

        await store.upsert(kb_id, chunks)

        # Verify chunks were inserted
        async with pg_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM chunks WHERE doc_id=$1", doc_id,
            )
            assert count == 2

    async def test_upsert_duplicate_doc_raises(self, store, pg_pool):
        """Same doc_id again should raise DuplicateDocumentError."""
        kb_id = f"kb_up_dup_{id(self)}"
        doc_id = f"doc_up_dup_{id(self)}"
        await self._ensure_kb(kb_id, pg_pool)

        chunks = [
            Chunk(
                id=f"{doc_id}:0", kb_id=kb_id, doc_id=doc_id,
                text="first", vector=_make_vec(0.1, 0.2, 0.3),
                metadata={},
            ),
        ]
        await store.upsert(kb_id, chunks)  # first — succeeds

        with pytest.raises(DuplicateDocumentError) as exc_info:
            await store.upsert(kb_id, chunks)  # second — should fail
        assert exc_info.value.code == 1201
        assert exc_info.value.http_status == 409

    async def test_search_by_vector(self, store, pg_pool):
        """Cosine-similarity search returns hits sorted by score DESC."""
        kb_id = f"kb_search_{id(self)}"
        doc_id = f"doc_search_{id(self)}"
        await self._ensure_kb(kb_id, pg_pool)

        # Insert chunks with distinct vectors (one-hot in first 3 dims)
        chunks = [
            Chunk(
                id=f"{doc_id}:0", kb_id=kb_id, doc_id=doc_id,
                text="apple pie", vector=_make_vec(1.0, 0.0, 0.0),
                metadata={"food": "pie"},
            ),
            Chunk(
                id=f"{doc_id}:1", kb_id=kb_id, doc_id=doc_id,
                text="banana bread", vector=_make_vec(0.0, 1.0, 0.0),
                metadata={"food": "bread"},
            ),
            Chunk(
                id=f"{doc_id}:2", kb_id=kb_id, doc_id=doc_id,
                text="cherry tart", vector=_make_vec(0.0, 0.0, 1.0),
                metadata={"food": "tart"},
            ),
        ]
        await store.upsert(kb_id, chunks)

        # Search for vectors close to apple pie
        hits = await store.search_by_vector(
            query_vector=_make_vec(0.95, 0.05, 0.0),
            top_k=3,
            kb_ids=[kb_id],
        )

        assert len(hits) >= 1
        assert all(isinstance(h, SearchHit) for h in hits)
        # The most similar hit should be apple pie (score closest to 1.0)
        assert hits[0].doc_id == doc_id
        assert hits[0].chunk_id == f"{doc_id}:0"

    async def test_search_cross_kb(self, store, pg_pool):
        """Search across multiple KBs returns combined results."""
        kb_a = f"kb_cross_a_{id(self)}"
        kb_b = f"kb_cross_b_{id(self)}"
        await self._ensure_kb(kb_a, pg_pool)
        await self._ensure_kb(kb_b, pg_pool)

        doc_a = f"doc_cross_a_{id(self)}"
        doc_b = f"doc_cross_b_{id(self)}"
        vec = _make_vec(0.5, 0.5, 0.0)

        await store.upsert(kb_a, [
            Chunk(id=f"{doc_a}:0", kb_id=kb_a, doc_id=doc_a,
                  text="from A", vector=vec, metadata={}),
        ])
        await store.upsert(kb_b, [
            Chunk(id=f"{doc_b}:0", kb_id=kb_b, doc_id=doc_b,
                  text="from B", vector=vec, metadata={}),
        ])

        hits = await store.search_by_vector(
            query_vector=vec, top_k=10, kb_ids=[kb_a, kb_b],
        )

        assert len(hits) == 2
        found_kbs = {h.kb_id for h in hits}
        assert kb_a in found_kbs
        assert kb_b in found_kbs

    async def test_search_empty_kb(self, store, pg_pool):
        """Search on a KB with no chunks returns empty list."""
        kb_id = f"kb_empty_{id(self)}"
        await self._ensure_kb(kb_id, pg_pool)

        hits = await store.search_by_vector(
            query_vector=_make_vec(0.1, 0.2, 0.3),
            top_k=5,
            kb_ids=[kb_id],
        )
        assert hits == []
