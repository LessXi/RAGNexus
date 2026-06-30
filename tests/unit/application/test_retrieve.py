"""Tests for RetrieveUseCase."""

from unittest.mock import AsyncMock, patch

import pytest

from ragnexus.adapters.rerank.noop import NoopRerankProvider
from ragnexus.adapters.rewrite.noop import NoopRewriteProvider
from ragnexus.application.retrieve_use_case import RetrieveUseCase
from ragnexus.core.errors import AppError
from ragnexus.domain.models import SearchHit
from ragnexus.domain.ports import RewriteResult


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
def mock_reranker():
    """RerankPort mock — 默认直通返回，各测试可按需覆盖 return_value。"""
    m = AsyncMock()
    return m


@pytest.fixture
def mock_rewriter():
    """RewritePort mock — 默认直通返回原始 query，各测试可按需覆盖。"""
    m = AsyncMock()

    async def _passthrough(*, query, kb_ids):
        return RewriteResult(
            original_query=query,
            rewritten_query=query,
            needs_rewrite=False,
            reason="mock 直通",
        )

    m.rewrite.side_effect = _passthrough
    return m


@pytest.fixture
def use_case(
    mock_kb_repo, mock_embedder, mock_store, mock_log_port, mock_reranker, mock_rewriter
):
    return RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=mock_rewriter,
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
async def test_retrieve_success(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_log_port,
    mock_reranker,
    sample_hits,
):
    """Valid query/kb_ids/top_k should embed, search, and return SearchHit list with scores."""
    kb_ids = ["kb_test"]
    top_k = 5

    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits

    result = await use_case.execute(query="test query", kb_ids=kb_ids, top_k=top_k)

    assert result == sample_hits
    assert all(isinstance(h, SearchHit) for h in result)
    assert all(isinstance(h.score, float) for h in result)

    mock_embedder.embed.assert_awaited_once_with(["test query"])
    # 默认 multiplier=1, min=0 → candidate_k == top_k
    candidate_k = max(top_k * 1, top_k + 0)
    mock_store.search_by_vector.assert_awaited_once_with(
        [0.1, 0.2, 0.3], candidate_k, kb_ids
    )
    mock_reranker.rerank.assert_awaited_once_with(
        query="test query",
        query_vector=[0.1, 0.2, 0.3],
        kb_ids=kb_ids,
        chunks=sample_hits,
        top_n=top_k,
    )
    mock_kb_repo.exists.assert_awaited_once_with("kb_test")

    # log_port.log should have been called via create_task (fire-and-forget)
    # We just verify it was called (the task may or may not have completed)
    import asyncio

    await asyncio.sleep(0.01)  # yield to let the fire-and-forget task run
    mock_log_port.log.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_logs_biz_event(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_log_port,
    mock_reranker,
    sample_hits,
):
    """Retrieve completion emits BIZ_EVENT log in finally block."""
    import asyncio

    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits

    with patch("ragnexus.core.logger.logger.info") as mock_info:
        await use_case.execute(query="test query", kb_ids=["kb_test"], top_k=5)
        await asyncio.sleep(0.01)  # yield to let the fire-and-forget task run

        # 找到 BIZ_EVENT 调用
        biz_calls = [
            call
            for call in mock_info.call_args_list
            if call.kwargs.get("extra", {}).get("event_type") == "BIZ_EVENT"
        ]
        assert len(biz_calls) == 1
        extra = biz_calls[0].kwargs["extra"]
        assert extra["event"] == "retrieve_completed"
        assert extra["kb_ids"] == ["kb_test"]
        assert extra["top_k"] == 5
        assert extra["hit_count"] == len(sample_hits)
        assert extra["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_query_empty(
    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port
):
    """Empty or whitespace-only query should raise ValidationError."""
    for bad_query in ("", "  "):
        with pytest.raises(AppError):
            await use_case.execute(query=bad_query, kb_ids=["kb_test"], top_k=5)
    mock_kb_repo.exists.assert_not_called()
    mock_embedder.embed.assert_not_called()
    mock_store.search_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_query_too_long(
    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port
):
    """Query longer than 2000 chars should raise ValidationError."""
    long_query = "A" * 2001
    with pytest.raises(AppError):
        await use_case.execute(query=long_query, kb_ids=["kb_test"], top_k=5)
    mock_kb_repo.exists.assert_not_called()
    mock_embedder.embed.assert_not_called()
    mock_store.search_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_kb_ids_empty(
    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port
):
    """Empty kb_ids list should raise ValidationError."""
    with pytest.raises(AppError):
        await use_case.execute(query="test query", kb_ids=[], top_k=5)
    mock_kb_repo.exists.assert_not_called()
    mock_embedder.embed.assert_not_called()
    mock_store.search_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_kb_ids_too_many(
    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port
):
    """More than 5 kb_ids should raise ValidationError."""
    with pytest.raises(AppError):
        await use_case.execute(
            query="test query", kb_ids=["a", "b", "c", "d", "e", "f"], top_k=5
        )
    mock_kb_repo.exists.assert_not_called()
    mock_embedder.embed.assert_not_called()
    mock_store.search_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_top_k_oob(
    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port
):
    """top_k < 1 or > 50 should raise ValidationError."""
    for bad_top_k in (0, 51):
        with pytest.raises(AppError):
            await use_case.execute(
                query="test query", kb_ids=["kb_test"], top_k=bad_top_k
            )
    mock_kb_repo.exists.assert_not_called()
    mock_embedder.embed.assert_not_called()
    mock_store.search_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_kb_not_found(
    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port
):
    """When any kb_id does not exist, should raise NotFoundError."""
    mock_kb_repo.exists.return_value = False

    with pytest.raises(AppError) as exc_info:
        await use_case.execute(query="test query", kb_ids=["kb_missing"], top_k=5)

    assert "kb_missing" in str(exc_info.value)
    mock_kb_repo.exists.assert_awaited_once_with("kb_missing")
    mock_embedder.embed.assert_not_called()
    mock_store.search_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_multiple_kb_not_found(
    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port
):
    """Should check all kb_ids and fail on first missing one."""

    # First exists, second does not
    async def exists_side_effect(kb_id):
        return {"kb_good": True, "kb_bad": False}[kb_id]

    mock_kb_repo.exists.side_effect = exists_side_effect

    with pytest.raises(AppError) as exc_info:
        await use_case.execute(
            query="test query",
            kb_ids=["kb_good", "kb_bad"],
            top_k=5,
        )
    assert "kb_bad" in str(exc_info.value)
    mock_embedder.embed.assert_not_called()
    mock_store.search_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_log_fire_and_forget(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_log_port,
    mock_reranker,
    sample_hits,
):
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits
    mock_log_port.log.side_effect = RuntimeError("log failure")

    # Should not propagate the log error
    result = await use_case.execute(query="test query", kb_ids=["kb_test"], top_k=5)

    assert result == sample_hits
    mock_reranker.rerank.assert_awaited_once()
    # Give the fire-and-forget task a chance to run/be swallowed
    import asyncio

    await asyncio.sleep(0.01)
    mock_log_port.log.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════
# rerank 注入测试 — Phase 4 Task 4.1-4.2
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_candidate_k_uses_multiplier(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_log_port,
    mock_reranker,
    mock_rewriter,
    sample_hits,
):
    """candidate_multiplier=3, min_candidates=0 → candidate_k = top_k * 3。"""
    uc = RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=mock_rewriter,
        candidate_multiplier=3,
        min_candidates=0,
    )
    top_k = 5
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits[:2]

    await uc.execute(query="q", kb_ids=["kb_test"], top_k=top_k)

    # candidate_k = max(5*3, 5+0) = 15
    mock_store.search_by_vector.assert_awaited_once_with(
        [0.1, 0.2, 0.3], 15, ["kb_test"]
    )


@pytest.mark.asyncio
async def test_candidate_k_uses_min_candidates(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_log_port,
    mock_reranker,
    mock_rewriter,
    sample_hits,
):
    """multiplier=1, min_candidates=10 → candidate_k = top_k + 10。"""
    uc = RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=mock_rewriter,
        candidate_multiplier=1,
        min_candidates=10,
    )
    top_k = 5
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits[:2]

    await uc.execute(query="q", kb_ids=["kb_test"], top_k=top_k)

    # candidate_k = max(5*1, 5+10) = 15
    mock_store.search_by_vector.assert_awaited_once_with(
        [0.1, 0.2, 0.3], 15, ["kb_test"]
    )


@pytest.mark.asyncio
async def test_candidate_k_takes_max(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_log_port,
    mock_reranker,
    mock_rewriter,
    sample_hits,
):
    """multiplier=2 给出 10，min_candidates=2 给出 7，取大者 10。"""
    uc = RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=mock_rewriter,
        candidate_multiplier=2,
        min_candidates=2,
    )
    top_k = 5
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits[:2]

    await uc.execute(query="q", kb_ids=["kb_test"], top_k=top_k)

    # candidate_k = max(5*2, 5+2) = 10
    mock_store.search_by_vector.assert_awaited_once_with(
        [0.1, 0.2, 0.3], 10, ["kb_test"]
    )


@pytest.mark.asyncio
async def test_rerank_called_with_correct_kwargs(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_log_port,
    mock_reranker,
    mock_rewriter,
    sample_hits,
):
    """reranker.rerank 使用正确的 keyword 参数调用。"""
    uc = RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=mock_rewriter,
    )
    top_k = 3
    query = "什么是 RAG？"
    kb_ids = ["kb_a", "kb_b"]
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.5, 0.6]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits[:1]

    await uc.execute(query=query, kb_ids=kb_ids, top_k=top_k)

    mock_reranker.rerank.assert_awaited_once_with(
        query=query,
        query_vector=[0.5, 0.6],
        kb_ids=kb_ids,
        chunks=sample_hits,
        top_n=top_k,
    )


async def test_rerank_result_is_returned(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_log_port,
    mock_reranker,
    mock_rewriter,
    sample_hits,
):
    """execute() 返回 rerank 后的结果，而非原始向量召回结果。"""
    uc = RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=mock_rewriter,
    )
    # 构造一个与向量召回不同的 rerank 返回（顺序或内容不同）
    reranked = [sample_hits[1], sample_hits[0]]  # 顺序反转
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = reranked

    result = await uc.execute(query="q", kb_ids=["kb_test"], top_k=5)

    assert result == reranked
    assert result != sample_hits  # 证明返回的是 rerank 结果
    mock_reranker.rerank.assert_awaited_once()


@pytest.mark.asyncio
async def test_noop_rerank_integration(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_log_port,
    sample_hits,
):
    """使用真实 NoopRerankProvider — chunks[:top_n] 截断语义端到端。"""
    uc = RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=NoopRerankProvider(),
        rewriter=NoopRewriteProvider(),
    )
    top_k = 1
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2]]
    mock_store.search_by_vector.return_value = sample_hits  # 2 条

    result = await uc.execute(query="q", kb_ids=["kb_test"], top_k=top_k)

    # NoopRerankProvider 返回 chunks[:top_n]，即只保留前 top_k 条
    assert len(result) == 1
    assert result[0] == sample_hits[0]


# ═══════════════════════════════════════════════════════════════════
# rewrite 注入测试 — Phase 6 Task 6.1-6.2
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rewriter_called_before_embed(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_rewriter,
):
    """rewriter.rewrite 在 embedder.embed 之前调用。"""
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2]]
    mock_store.search_by_vector.return_value = []

    await use_case.execute(query="test query", kb_ids=["kb1"], top_k=3)

    mock_rewriter.rewrite.assert_awaited_once_with(query="test query", kb_ids=["kb1"])


@pytest.mark.asyncio
async def test_rewritten_query_used_for_embed(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_rewriter,
):
    """rewrite 后 embed 使用 rewritten_query，而非原始 query。"""
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2]]
    mock_store.search_by_vector.return_value = []

    # 覆写 mock_rewriter，返回不同改写结果
    mock_rewriter.rewrite.side_effect = None
    mock_rewriter.rewrite.return_value = RewriteResult(
        original_query="hello world",
        rewritten_query="hello world technical definition",
        needs_rewrite=True,
        reason="优化查询",
    )

    await use_case.execute(query="hello world", kb_ids=["kb1"], top_k=3)

    # embed 用改写后的 query
    mock_embedder.embed.assert_awaited_once_with(["hello world technical definition"])


@pytest.mark.asyncio
async def test_rerank_uses_original_query_rewritten_vector(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_reranker,
    mock_rewriter,
):
    """rerank 用原始 query 做相关性判断，query_vector 用改写后的向量。"""
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.9, 0.1]]
    mock_store.search_by_vector.return_value = []
    mock_reranker.rerank.return_value = []

    # 覆写 mock_rewriter，改写查询
    mock_rewriter.rewrite.side_effect = None
    mock_rewriter.rewrite.return_value = RewriteResult(
        original_query="what is RAG",
        rewritten_query="retrieval augmented generation definition",
        needs_rewrite=True,
        reason="扩展缩写",
    )

    await use_case.execute(query="what is RAG", kb_ids=["kb1"], top_k=5)

    # rerank 的 query 参数用原始 query（相关性判断）
    mock_reranker.rerank.assert_awaited_once()
    rerank_kwargs = mock_reranker.rerank.call_args.kwargs
    assert rerank_kwargs["query"] == "what is RAG"
    # query_vector 是改写后嵌入的向量
    assert rerank_kwargs["query_vector"] == [0.9, 0.1]


@pytest.mark.asyncio
async def test_noop_rewrite_integration(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_log_port,
    mock_reranker,
    sample_hits,
):
    """使用真实 NoopRewriteProvider — 禁用改写时直通，行为不变。"""
    uc = RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=NoopRewriteProvider(),
    )
    query = "test query"
    kb_ids = ["kb_test"]
    top_k = 2
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.5, 0.5]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits[:top_k]

    result = await uc.execute(query=query, kb_ids=kb_ids, top_k=top_k)

    # NoopRewriteProvider 直通：embed 用原始 query
    mock_embedder.embed.assert_awaited_once_with([query])
    # 其他行为不变
    mock_reranker.rerank.assert_awaited_once()
    mock_store.search_by_vector.assert_awaited_once()
    assert len(result) == top_k
