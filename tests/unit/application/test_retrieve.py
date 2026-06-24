"""Tests for RetrieveUseCase."""

from unittest.mock import AsyncMock, PropertyMock

import pytest
from ragnexus.domain.errors import ValidationError, NotFoundError
from ragnexus.domain.models import SearchHit

from ragnexus.application.retrieve_use_case import RetrieveUseCase


@pytest.fixture
def mock_kb_repo():
    return AsyncMock()


@pytest.fixture
def mock_embedder():
    return AsyncMock()


@pytest.fixture
def mock_store():
    return AsyncMock()


@pytest.fixture
def mock_log_port():
    return AsyncMock()


@pytest.fixture
def use_case(mock_kb_repo, mock_embedder, mock_store, mock_log_port):
    return RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
    )


@pytest.fixture
def sample_hits():
    return [
        SearchHit(
            chunk_id="kb_test:0",
            kb_id="kb_test",
            doc_id="doc_1",
            score=0.95,
            text="relevant chunk",
            metadata={},
        ),
        SearchHit(
            chunk_id="kb_test:1",
            kb_id="kb_test",
            doc_id="doc_1",
            score=0.85,
            text="another chunk",
            metadata={},
        ),
    ]


@pytest.mark.asyncio
async def test_retrieve_success(use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port, sample_hits):
    """Valid query/kb_ids/top_k should embed, search, and return SearchHit list with scores."""
    kb_ids = ["kb_test"]
    top_k = 5

    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
    mock_store.search_by_vector.return_value = sample_hits

    result = await use_case.execute(query="test query", kb_ids=kb_ids, top_k=top_k)

    assert result == sample_hits
    assert all(isinstance(h, SearchHit) for h in result)
    assert all(isinstance(h.score, float) for h in result)

    mock_embedder.embed.assert_awaited_once_with(["test query"])
    mock_store.search_by_vector.assert_awaited_once_with(
        [0.1, 0.2, 0.3], top_k, kb_ids
    )
    mock_kb_repo.exists.assert_awaited_once_with("kb_test")

    # log_port.log should have been called via create_task (fire-and-forget)
    # We just verify it was called (the task may or may not have completed)
    import asyncio
    await asyncio.sleep(0.01)  # yield to let the fire-and-forget task run
    mock_log_port.log.assert_awaited_once()


@pytest.mark.asyncio
async def test_query_empty(use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port):
    """Empty or whitespace-only query should raise ValidationError."""
    for bad_query in ("", "  "):
        with pytest.raises(ValidationError):
            await use_case.execute(query=bad_query, kb_ids=["kb_test"], top_k=5)
    mock_kb_repo.exists.assert_not_called()
    mock_embedder.embed.assert_not_called()
    mock_store.search_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_query_too_long(use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port):
    """Query longer than 2000 chars should raise ValidationError."""
    long_query = "A" * 2001
    with pytest.raises(ValidationError):
        await use_case.execute(query=long_query, kb_ids=["kb_test"], top_k=5)
    mock_kb_repo.exists.assert_not_called()
    mock_embedder.embed.assert_not_called()
    mock_store.search_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_kb_ids_empty(use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port):
    """Empty kb_ids list should raise ValidationError."""
    with pytest.raises(ValidationError):
        await use_case.execute(query="test query", kb_ids=[], top_k=5)
    mock_kb_repo.exists.assert_not_called()
    mock_embedder.embed.assert_not_called()
    mock_store.search_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_kb_ids_too_many(use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port):
    """More than 5 kb_ids should raise ValidationError."""
    with pytest.raises(ValidationError):
        await use_case.execute(query="test query", kb_ids=["a", "b", "c", "d", "e", "f"], top_k=5)
    mock_kb_repo.exists.assert_not_called()
    mock_embedder.embed.assert_not_called()
    mock_store.search_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_top_k_oob(use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port):
    """top_k < 1 or > 50 should raise ValidationError."""
    for bad_top_k in (0, 51):
        with pytest.raises(ValidationError):
            await use_case.execute(query="test query", kb_ids=["kb_test"], top_k=bad_top_k)
    mock_kb_repo.exists.assert_not_called()
    mock_embedder.embed.assert_not_called()
    mock_store.search_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_kb_not_found(use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port):
    """When any kb_id does not exist, should raise NotFoundError."""
    mock_kb_repo.exists.return_value = False

    with pytest.raises(NotFoundError) as exc_info:
        await use_case.execute(query="test query", kb_ids=["kb_missing"], top_k=5)

    assert "kb_missing" in str(exc_info.value)
    mock_kb_repo.exists.assert_awaited_once_with("kb_missing")
    mock_embedder.embed.assert_not_called()
    mock_store.search_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_multiple_kb_not_found(use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port):
    """Should check all kb_ids and fail on first missing one."""
    # First exists, second does not
    async def exists_side_effect(kb_id):
        return {"kb_good": True, "kb_bad": False}[kb_id]

    mock_kb_repo.exists.side_effect = exists_side_effect

    with pytest.raises(NotFoundError) as exc_info:
        await use_case.execute(
            query="test query",
            kb_ids=["kb_good", "kb_bad"],
            top_k=5,
        )
    assert "kb_bad" in str(exc_info.value)
    mock_embedder.embed.assert_not_called()
    mock_store.search_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_log_fire_and_forget(use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port, sample_hits):
    """When log_port.log raises, the exception should be swallowed (fire-and-forget)."""
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_log_port.log.side_effect = RuntimeError("log failure")

    # Should not propagate the log error
    result = await use_case.execute(query="test query", kb_ids=["kb_test"], top_k=5)

    assert result == sample_hits
    # Give the fire-and-forget task a chance to run/be swallowed
    import asyncio
    await asyncio.sleep(0.01)
    mock_log_port.log.assert_awaited_once()
