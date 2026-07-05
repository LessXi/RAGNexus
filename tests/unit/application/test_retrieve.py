"""Tests for RetrieveUseCase."""

from unittest.mock import AsyncMock, patch

import pytest

from ragnexus.adapters.rerank.noop import NoopRerankProvider
from ragnexus.adapters.rewrite.noop import NoopRewriteProvider
from ragnexus.adapters.rewrite.pipeline import QueryPipeline
from ragnexus.adapters.rewrite.synonym_expander import SynonymExpander
from ragnexus.application.retrieve_use_case import RetrieveUseCase
from ragnexus.core.errors import AppError
from ragnexus.domain.models import RetrieveResult, SearchHit
from ragnexus.domain.ports import QueryProcessResult


@pytest.fixture
def mock_kb_repo():
    mock = AsyncMock()
    mock.get.return_value = None
    mock.pool = AsyncMock()
    mock.pool.fetchval.return_value = 1
    return mock


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
def mock_keyword_store():
    return AsyncMock()


@pytest.fixture
def mock_reranker():
    """RerankPort mock — 默认直通返回，各测试可按需覆盖 return_value。"""
    m = AsyncMock()
    return m


@pytest.fixture
def mock_pipeline():
    """QueryPipeline mock — 默认直通返回原始 query。"""
    m = AsyncMock()

    async def _passthrough(
        *, raw_query, kb_ids, kb_context=None, synonyms=None, enabled=True
    ):
        return QueryProcessResult(
            raw_query=raw_query,
            effective_query=raw_query,
            search_query=raw_query,
            needs_rewrite=False,
            strategy="noop",
            rewrite_latency_ms=0,
            degraded=False,
            degraded_reason=None,
            synonym_applied=False,
            synonym_expansions=[],
        )

    m.process.side_effect = _passthrough
    return m


@pytest.fixture
def use_case(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_keyword_store,
    mock_log_port,
    mock_reranker,
    mock_pipeline,
):
    return RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=None,
        pipeline=mock_pipeline,
        keyword_store=mock_keyword_store,
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
    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits

    result = await use_case.execute(
        tenant_id="test-tenant", query="test query", kb_ids=kb_ids, top_k=top_k
    )

    assert isinstance(result, RetrieveResult)
    assert result.hits == sample_hits
    assert all(isinstance(h, SearchHit) for h in result.hits)
    assert all(isinstance(h.score, float) for h in result.hits)
    mock_embedder.embed.assert_awaited_once_with(["test query", "test query"])
    # 默认 candidate_k=20
    mock_store.search_by_vector.assert_awaited_once_with([0.1, 0.2, 0.3], 20, kb_ids)
    mock_reranker.rerank.assert_awaited_once()
    rerank_kwargs = mock_reranker.rerank.await_args.kwargs
    assert rerank_kwargs["query"] == "test query"
    assert rerank_kwargs["query_vector"] == [0.4, 0.5, 0.6]
    assert rerank_kwargs["kb_ids"] == kb_ids
    assert [h.chunk_id for h in rerank_kwargs["chunks"]] == [
        h.chunk_id for h in sample_hits
    ]
    assert rerank_kwargs["top_n"] == top_k
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
    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits

    with patch("ragnexus.core.logger.logger.info") as mock_info:
        await use_case.execute(
            tenant_id="test-tenant", query="test query", kb_ids=["kb_test"], top_k=5
        )
        await asyncio.sleep(0.01)  # yield to let the fire-and-forget task run

        # 找到 BIZ_EVENT 调用（hybrid 模式下有 keyword_search_done + retrieve_completed 两个）
        biz_calls = [
            call
            for call in mock_info.call_args_list
            if call.kwargs.get("extra", {}).get("event_type") == "BIZ_EVENT"
        ]
        # 过滤出 retrieve_completed
        rc_calls = [
            c for c in biz_calls if c.kwargs["extra"]["event"] == "retrieve_completed"
        ]
        assert len(rc_calls) == 1
        extra = rc_calls[0].kwargs["extra"]
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
            await use_case.execute(
                tenant_id="test-tenant", query=bad_query, kb_ids=["kb_test"], top_k=5
            )
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
        await use_case.execute(
            tenant_id="test-tenant", query=long_query, kb_ids=["kb_test"], top_k=5
        )
    mock_kb_repo.exists.assert_not_called()
    mock_embedder.embed.assert_not_called()
    mock_store.search_by_vector.assert_not_called()


@pytest.mark.asyncio
async def test_kb_ids_empty(
    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port
):
    """Empty kb_ids list should raise ValidationError."""
    with pytest.raises(AppError):
        await use_case.execute(
            tenant_id="test-tenant", query="test query", kb_ids=[], top_k=5
        )
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
            tenant_id="test-tenant",
            query="test query",
            kb_ids=["a", "b", "c", "d", "e", "f"],
            top_k=5,
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
                tenant_id="test-tenant",
                query="test query",
                kb_ids=["kb_test"],
                top_k=bad_top_k,
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
        await use_case.execute(
            tenant_id="test-tenant", query="test query", kb_ids=["kb_missing"], top_k=5
        )

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
            tenant_id="test-tenant",
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
    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits
    mock_log_port.log.side_effect = RuntimeError("log failure")

    # Should not propagate the log error
    result = await use_case.execute(
        tenant_id="test-tenant", query="test query", kb_ids=["kb_test"], top_k=5
    )

    assert result.hits == sample_hits
    mock_reranker.rerank.assert_awaited_once()
    # Give the fire-and-forget task a chance to run/be swallowed
    import asyncio

    await asyncio.sleep(0.01)
    mock_log_port.log.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════
# rerank 注入测试 — Phase 4 Task 4.1-4.2
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_candidate_k_passed_to_vector_search(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_keyword_store,
    mock_log_port,
    mock_reranker,
    mock_pipeline,
    sample_hits,
):
    """candidate_k=15 时，search_by_vector 收到 candidate_k=15。"""
    uc = RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=None,
        pipeline=mock_pipeline,
        keyword_store=mock_keyword_store,
        candidate_k=15,
    )
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits[:2]

    await uc.execute(tenant_id="test-tenant", query="q", kb_ids=["kb_test"], top_k=5)

    mock_store.search_by_vector.assert_awaited_once_with(
        [0.1, 0.2, 0.3], 15, ["kb_test"]
    )


@pytest.mark.asyncio
async def test_candidate_k_passed_to_keyword_search(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_keyword_store,
    mock_log_port,
    mock_reranker,
    mock_pipeline,
    sample_hits,
):
    """candidate_k=25 时，BM25 search 也收到 candidate_k=25。"""
    uc = RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=None,
        pipeline=mock_pipeline,
        keyword_store=mock_keyword_store,
        candidate_k=25,
    )
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_keyword_store.search_by_keyword.return_value = []
    mock_reranker.rerank.return_value = sample_hits[:2]

    await uc.execute(tenant_id="test-tenant", query="q", kb_ids=["kb_test"], top_k=5)

    mock_keyword_store.search_by_keyword.assert_awaited_once_with("kb_test", "q", 25)


@pytest.mark.asyncio
async def test_rerank_called_with_correct_kwargs(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_keyword_store,
    mock_log_port,
    mock_reranker,
    mock_pipeline,
    sample_hits,
):
    """reranker.rerank 使用正确的 keyword 参数调用。"""
    uc = RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=None,
        pipeline=mock_pipeline,
        keyword_store=mock_keyword_store,
    )
    top_k = 3
    query = "什么是 RAG？"
    kb_ids = ["kb_a", "kb_b"]
    mock_kb_repo.exists.return_value = True
    mock_kb_repo.pool.fetchval.return_value = len(kb_ids)
    mock_embedder.embed.return_value = [[0.5, 0.6], [0.7, 0.8]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits[:1]

    await uc.execute(tenant_id="test-tenant", query=query, kb_ids=kb_ids, top_k=top_k)

    mock_reranker.rerank.assert_awaited_once()
    rerank_kwargs = mock_reranker.rerank.await_args.kwargs
    assert rerank_kwargs["query"] == query
    assert rerank_kwargs["query_vector"] == [0.7, 0.8]
    assert rerank_kwargs["kb_ids"] == kb_ids
    assert [h.chunk_id for h in rerank_kwargs["chunks"]] == [
        h.chunk_id for h in sample_hits
    ]
    assert rerank_kwargs["top_n"] == 5  # 默认 rerank_top_n=5


@pytest.mark.asyncio
async def test_rerank_result_is_returned(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_keyword_store,
    mock_log_port,
    mock_reranker,
    mock_pipeline,
    sample_hits,
):
    """execute() 返回 rerank 后的结果，而非原始向量召回结果。"""
    uc = RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=None,
        pipeline=mock_pipeline,
        keyword_store=mock_keyword_store,
    )
    # 构造一个与向量召回不同的 rerank 返回（顺序或内容不同）
    reranked = [sample_hits[1], sample_hits[0]]  # 顺序反转
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2], [0.3, 0.4]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = reranked

    result = await uc.execute(
        tenant_id="test-tenant", query="q", kb_ids=["kb_test"], top_k=5
    )

    assert result.hits == reranked
    assert result.hits != sample_hits  # 证明返回的是 rerank 结果
    mock_reranker.rerank.assert_awaited_once()


@pytest.mark.asyncio
async def test_noop_rerank_integration(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_keyword_store,
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
        keyword_store=mock_keyword_store,
    )
    top_k = 1
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2], [0.3, 0.4]]
    mock_store.search_by_vector.return_value = sample_hits  # 2 条

    result = await uc.execute(
        tenant_id="test-tenant", query="q", kb_ids=["kb_test"], top_k=top_k
    )

    assert len(result.hits) == 2  # rerank_top_n=5, Noop 保留全部 2 条
    assert result.hits[0].chunk_id == sample_hits[0].chunk_id


# ═══════════════════════════════════════════════════════════════════
# query processing pipeline 注入测试 — Stage 6
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pipeline_called_before_embed(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_pipeline,
):
    """pipeline.process 在 embedder.embed 之前调用。"""
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2], [0.3, 0.4]]
    mock_store.search_by_vector.return_value = []

    await use_case.execute(
        tenant_id="test-tenant", query="test query", kb_ids=["kb1"], top_k=3
    )

    mock_pipeline.process.assert_awaited_once()
    call_kwargs = mock_pipeline.process.call_args.kwargs
    assert call_kwargs["raw_query"] == "test query"
    assert call_kwargs["kb_ids"] == ["kb1"]


@pytest.mark.asyncio
async def test_rewritten_query_used_for_embed(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_pipeline,
):
    """pipeline 改写后 embed 使用 search_query，而非原始 query。"""
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.1, 0.2], [0.3, 0.4]]
    mock_store.search_by_vector.return_value = []

    # 覆写 mock_pipeline，返回不同 search_query
    mock_pipeline.process.side_effect = None
    mock_pipeline.process.return_value = QueryProcessResult(
        raw_query="hello world",
        effective_query="hello world technical definition",
        search_query="hello world technical definition search",
        needs_rewrite=True,
        strategy="rewrite",
        rewrite_latency_ms=10,
        degraded=False,
        degraded_reason=None,
        synonym_applied=True,
        synonym_expansions=["search"],
    )

    await use_case.execute(
        tenant_id="test-tenant", query="hello world", kb_ids=["kb1"], top_k=3
    )

    # embed 用 search_query（第一个）+ 原始 query（第二个）
    mock_embedder.embed.assert_awaited_once_with(
        ["hello world technical definition search", "hello world"]
    )


@pytest.mark.asyncio
async def test_rerank_uses_original_query_pipeline_vector(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_reranker,
    mock_pipeline,
):
    """rerank 用原始 query 做相关性判断，query_vector 用原始 query 的 embedding。"""
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [
        [0.9, 0.1],
        [0.2, 0.3],
    ]  # [search_query向量, 原始向量]
    mock_store.search_by_vector.return_value = []
    mock_reranker.rerank.return_value = []

    # 覆写 mock_pipeline，改写查询
    mock_pipeline.process.side_effect = None
    mock_pipeline.process.return_value = QueryProcessResult(
        raw_query="what is RAG",
        effective_query="retrieval augmented generation definition",
        search_query="retrieval augmented generation definition",
        needs_rewrite=True,
        strategy="rewrite",
        rewrite_latency_ms=12,
        degraded=False,
        degraded_reason=None,
        synonym_applied=False,
        synonym_expansions=[],
    )

    await use_case.execute(
        tenant_id="test-tenant", query="what is RAG", kb_ids=["kb1"], top_k=5
    )

    # rerank 的 query 参数用原始 query（相关性判断）
    mock_reranker.rerank.assert_awaited_once()
    rerank_kwargs = mock_reranker.rerank.call_args.kwargs
    assert rerank_kwargs["query"] == "what is RAG"
    # query_vector 现在是原始 query 的 embedding（第二个向量），用于缓存匹配
    assert rerank_kwargs["query_vector"] == [0.2, 0.3]


@pytest.mark.asyncio
async def test_noop_pipeline_integration(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_keyword_store,
    mock_log_port,
    mock_reranker,
    sample_hits,
):
    """使用真实 NoopRewriteProvider + SynonymExpander + QueryPipeline — 禁用改写时直通。"""
    from ragnexus.adapters.rewrite.noop import NoopRewriteProvider

    noop_rewriter = NoopRewriteProvider()
    expander = SynonymExpander()
    pipeline = QueryPipeline(noop_rewriter, expander)

    uc = RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=None,
        pipeline=pipeline,
        keyword_store=mock_keyword_store,
    )
    query = "test query"
    kb_ids = ["kb_test"]
    top_k = 2
    mock_kb_repo.exists.return_value = True
    mock_embedder.embed.return_value = [[0.5, 0.5], [0.6, 0.6]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits[:top_k]

    result = await uc.execute(
        tenant_id="test-tenant", query=query, kb_ids=kb_ids, top_k=top_k
    )

    # Noop pipeline 直通：embed 用原始 query（两次，search_query 和原始相同）
    mock_embedder.embed.assert_awaited_once_with([query, query])
    # 其他行为不变
    mock_reranker.rerank.assert_awaited_once()
    mock_store.search_by_vector.assert_awaited_once()
    assert len(result.hits) == top_k


# ═══════════════════════════════════════════════════════════════════
# Stage 12 验收场景测试
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario_12_1_no_query_options_noop(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_keyword_store,
    mock_log_port,
    mock_reranker,
    mock_pipeline,
    sample_hits,
):
    """12.1: 不传 query_options + 无 settings → 行为与改前一致，query_processing 为 null。

    验证：pipeline 以 enabled=False 调用（env 默认 false），
    返回 noop 结果，query_processing 序列化为 strategy="noop" + synonym_applied=False，
    这在 router 层会被过滤为 null。
    """
    # Arrange: env 默认 QUERY_REWRITE_ENABLED=false（不设置 env var），无 KB settings
    mock_kb_repo.exists.return_value = True
    mock_kb_repo.get.return_value = None  # 无 KB 对象 → 无 settings
    mock_embedder.embed.return_value = [[0.1, 0.2], [0.3, 0.4]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits[:2]

    result = await RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=None,
        pipeline=mock_pipeline,
        keyword_store=mock_keyword_store,
    ).execute(
        tenant_id="test-tenant",
        query="test query",
        kb_ids=["kb1"],
        top_k=2,
        # 不传 query_options
    )

    # pipeline 被 enabled=False 调用
    mock_pipeline.process.assert_awaited_once()
    call_kwargs = mock_pipeline.process.call_args.kwargs
    assert call_kwargs["enabled"] is False
    assert call_kwargs["raw_query"] == "test query"

    # 结果可正常返回（行为与改前一致）
    assert len(result.hits) == 2
    assert result.degraded is False

    # query_processing 存在但为 noop — router 会过滤为 null
    assert result.query_processing is not None
    assert result.query_processing["strategy"] == "noop"
    assert result.query_processing["synonym_applied"] is False


@pytest.mark.asyncio
async def test_scenario_12_7_cross_kb_isolation(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_keyword_store,
    mock_log_port,
    mock_reranker,
    mock_pipeline,
    sample_hits,
):
    """12.7: 跨库隔离 — KB_A 词表不影响 KB_B。

    验证：当 kb_ids=["kb_a", "kb_b"] 时，只有 kb_ids[0]（KB_A）的 settings
    被读取并传给 pipeline，KB_B 的 settings 不会被读取。
    """
    from unittest.mock import MagicMock

    # 构造 KB_A（有 synonyms）和 KB_B（无）
    kb_a = MagicMock()
    kb_a.name = "KB_A"
    kb_a.description = "Knowledge Base A"
    kb_a.settings = {"synonyms": [{"terms": ["AI"], "expand": ["人工智能"]}]}

    kb_b = MagicMock()
    kb_b.name = "KB_B"
    kb_b.description = "Knowledge Base B"
    kb_b.settings = {"synonyms": [{"terms": ["ML"], "expand": ["机器学习"]}]}

    # kb_repo.get 只返回 kb_ids[0] 的 KB（代码中只调用了 kb_ids[0]）
    # 这里 mock 返回 KB_A 来验证其 synonyms 被使用
    mock_kb_repo.get.return_value = kb_a
    mock_kb_repo.exists.return_value = True
    # ownership 校验需返回 2（2 个 unique KB）
    mock_kb_repo.pool.fetchval.return_value = 2
    mock_embedder.embed.return_value = [[0.1, 0.2], [0.3, 0.4]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits[:2]

    uc = RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=None,
        pipeline=mock_pipeline,
        keyword_store=mock_keyword_store,
    )

    await uc.execute(
        tenant_id="test-tenant",
        query="AI test",
        kb_ids=["kb_a", "kb_b"],
        top_k=2,
        query_options={"enabled": True},
    )

    # 验证 pipeline 被调用时 synonyms 来自 KB_A
    call_kwargs = mock_pipeline.process.call_args.kwargs
    assert call_kwargs["synonyms"] == [{"terms": ["AI"], "expand": ["人工智能"]}]
    # KB_B 的 settings 未被读取（mock_kb_repo.get 只被调用一次，参数为 "kb_a"）
    mock_kb_repo.get.assert_awaited_once_with("kb_a")


@pytest.mark.asyncio
async def test_scenario_12_10_enabled_false_priority(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_keyword_store,
    mock_log_port,
    mock_reranker,
    mock_pipeline,
    sample_hits,
):
    """12.10: enabled=false + strategy="rewrite" → enabled 优先，query_processing 为 null。

    验证：当 query_options={'enabled': False, 'strategy': 'rewrite'} 时，
    pipeline 以 enabled=False 调用，忽略 strategy 字段。
    返回的 query_processing 为 noop（router 层会过滤为 null）。
    """
    mock_kb_repo.exists.return_value = True
    mock_kb_repo.get.return_value = None
    mock_embedder.embed.return_value = [[0.1, 0.2], [0.3, 0.4]]
    mock_store.search_by_vector.return_value = sample_hits
    mock_reranker.rerank.return_value = sample_hits[:2]

    uc = RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=None,
        pipeline=mock_pipeline,
        keyword_store=mock_keyword_store,
    )

    result = await uc.execute(
        tenant_id="test-tenant",
        query="test query",
        kb_ids=["kb1"],
        top_k=2,
        query_options={"enabled": False, "strategy": "rewrite"},
    )

    # enabled=False 优先 → pipeline 以 enabled=False 调用
    call_kwargs = mock_pipeline.process.call_args.kwargs
    assert call_kwargs["enabled"] is False

    # 结果正常返回
    assert len(result.hits) == 2
    # query_processing 为 noop（router 会过滤为 null）
    assert result.query_processing is not None
    assert result.query_processing["strategy"] == "noop"
    assert result.query_processing["synonym_applied"] is False
    # needs_rewrite 为 false（未执行改写）
    assert result.query_processing["needs_rewrite"] is False
