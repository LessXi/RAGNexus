"""Tests for PgVectorStore adapter — mock asyncpg pool."""

import json
from unittest.mock import AsyncMock, Mock

import pytest

from ragnexus.domain.errors import DuplicateDocumentError
from ragnexus.domain.models import Chunk, SearchHit


class _AcquireCM:
    """Async context manager simulating ``pool.acquire()``."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


class _TransactionCM:
    """Async context manager simulating ``conn.transaction()``."""

    async def __aenter__(self):
        return None

    async def __aexit__(self, *args):
        pass


@pytest.fixture
def sample_chunks():
    """Two chunks sharing the same doc_id for upsert tests."""
    return [
        Chunk(
            id="doc_test:0",
            kb_id="kb_test",
            doc_id="doc_test",
            text="chunk zero",
            vector=[0.1, 0.2, 0.3],
            metadata={"chunk_index": 0, "filename": "test.md"},
        ),
        Chunk(
            id="doc_test:1",
            kb_id="kb_test",
            doc_id="doc_test",
            text="chunk one",
            vector=[0.4, 0.5, 0.6],
            metadata={"chunk_index": 1, "filename": "test.md"},
        ),
    ]


@pytest.fixture
def mock_conn():
    """Return a mock connection with transaction() as sync Mock returning a
    real async context manager, so ``async with conn.transaction():`` works.
    """
    conn = AsyncMock(name="conn")
    conn.transaction = Mock(return_value=_TransactionCM())
    return conn


@pytest.fixture
def mock_pool(mock_conn):
    """Return a mock pool whose acquire() yields mock_conn.

    We use a plain Mock for ``acquire`` instead of AsyncMock because
    calling an AsyncMock returns a coroutine (not an async context
    manager), which would break ``async with pool.acquire() as conn:``.
    """
    pool = Mock(name="pool")
    pool.acquire.return_value = _AcquireCM(mock_conn)
    return pool


@pytest.fixture
def pg_store(mock_pool):
    """PgVectorStore with pool injected directly (bypass connect())."""
    from ragnexus.adapters.vector_store.pgvector import PgVectorStore

    store = PgVectorStore(
        dsn="postgresql://t:t@localhost:5432/t",
    )
    store.pool = mock_pool
    return store


# ── upsert ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_new_doc(pg_store, mock_conn, sample_chunks):
    """INSERT document + chunks when doc_id is new."""
    mock_conn.fetchval.return_value = None  # no duplicate

    await pg_store.upsert("kb_test", sample_chunks)

    # 1) duplicate check
    mock_conn.fetchval.assert_awaited_once_with(
        "SELECT 1 FROM chunks WHERE doc_id = $1 LIMIT 1",
        "doc_test",
    )

    # 2) documents insert
    mock_conn.execute.assert_awaited_once()
    sql, *params = mock_conn.execute.await_args.args
    assert "INSERT INTO documents" in sql
    assert params[0] == "doc_test"

    # 3) chunks executemany
    mock_conn.executemany.assert_awaited_once()
    exec_sql, exec_rows = mock_conn.executemany.await_args.args
    assert "INSERT INTO chunks" in exec_sql
    assert len(exec_rows) == 2
    assert exec_rows[0][0] == "doc_test:0"
    assert exec_rows[1][0] == "doc_test:1"
    assert json.loads(exec_rows[0][4])["chunk_index"] == 0
    assert exec_rows[0][5] == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_upsert_duplicate_doc(pg_store, mock_conn, sample_chunks):
    """Duplicate doc_id raises DuplicateDocumentError with code 1201."""
    mock_conn.fetchval.return_value = 1  # doc already exists

    with pytest.raises(DuplicateDocumentError) as exc_info:
        await pg_store.upsert("kb_test", sample_chunks)

    assert exc_info.value.code == 1201
    assert exc_info.value.http_status == 409
    mock_conn.execute.assert_not_called()
    mock_conn.executemany.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_race_condition(pg_store, mock_conn, sample_chunks):
    """When executemany raises UniqueViolationError → DuplicateDocumentError with code 1201."""
    import asyncpg

    mock_conn.fetchval.return_value = None  # application-level check passes
    mock_conn.executemany.side_effect = asyncpg.UniqueViolationError("duplicate key value")

    with pytest.raises(DuplicateDocumentError) as exc_info:
        await pg_store.upsert("kb_test", sample_chunks)

    assert exc_info.value.code == 1201
    assert exc_info.value.http_status == 409


# ── search_by_vector ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_by_vector(pg_store, mock_conn):
    """Returns SearchHit[] sorted by score DESC (SQL ORDER BY)."""
    mock_conn.fetch.return_value = [
        {
            "id": "doc_a:0",
            "kb_id": "kb_a",
            "doc_id": "doc_a",
            "text": "chunk A",
            "score": 0.92,
            "metadata": json.dumps({"chunk_index": 0}),
        },
        {
            "id": "doc_b:1",
            "kb_id": "kb_b",
            "doc_id": "doc_b",
            "text": "chunk B",
            "score": 0.65,
            "metadata": json.dumps({"chunk_index": 1}),
        },
    ]

    hits = await pg_store.search_by_vector(
        query_vector=[0.1, 0.2, 0.3],
        top_k=5,
        kb_ids=["kb_a", "kb_b"],
    )

    assert len(hits) == 2
    assert all(isinstance(h, SearchHit) for h in hits)
    assert hits[0].score == 0.92
    assert hits[0].chunk_id == "doc_a:0"
    assert hits[0].doc_id == "doc_a"
    assert hits[0].text == "chunk A"
    assert hits[0].metadata == {"chunk_index": 0}
    assert hits[1].score == 0.65
    assert hits[1].chunk_id == "doc_b:1"
    assert hits[1].kb_id == "kb_b"
