"""Phase 5: 双 embedding → 并行召回 → RRF 融合 测试。

测试 4 个核心场景：
- hybrid 模式：向量 + BM25 双路召回 → RRF 融合
- vector 模式：仅向量召回，直通 rerank
- bm25 模式：仅 BM25 召回，直通 rerank
- keyword search 失败降级：BM25 抛异常返回 []，不中断整体流程
"""

from unittest.mock import AsyncMock

import pytest

from ragnexus.application.retrieve_use_case import RetrieveUseCase
from ragnexus.domain.models import RetrieveResult, SearchHit
from ragnexus.domain.ports import QueryProcessResult


def _make_hit(
    chunk_id: str, kb_id: str = "kb1", score: float = 0.9, text: str = ""
) -> SearchHit:
    """快捷构造 SearchHit。"""
    return SearchHit(
        chunk_id=chunk_id,
        kb_id=kb_id,
        doc_id=f"doc_{chunk_id}",
        score=score,
        text=text or f"chunk {chunk_id} content",
        metadata={},
    )


@pytest.fixture
def mock_kb_repo():
    repo = AsyncMock()
    repo.exists.return_value = True
    repo.get.return_value = None
    repo.pool = AsyncMock()
    repo.pool.fetchval.return_value = 1
    return repo


@pytest.fixture
def mock_embedder():
    m = AsyncMock()
    m.embed.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    return m


@pytest.fixture
def mock_store():
    return AsyncMock()


@pytest.fixture
def mock_keyword_store():
    return AsyncMock()


@pytest.fixture
def mock_log_port():
    return AsyncMock()


@pytest.fixture
def mock_reranker():
    """RerankPort mock — 默认直通返回输入。"""
    m = AsyncMock()

    async def _passthrough(*, query, query_vector, kb_ids, chunks, top_n):
        return chunks[:top_n]

    m.rerank.side_effect = _passthrough
    return m


@pytest.fixture
def mock_pipeline():
    """QueryPipeline mock — 默认直通返回原始 query。"""
    m = AsyncMock()

    async def _passthrough(
        *, raw_query, kb_ids, kb_contexts=None, synonyms=None, enabled=True
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


# ═══════════════════════════════════════════════════════════════════
# hybrid 模式 — 双路召回 + RRF 融合
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_hybrid_mode(
    use_case,
    mock_embedder,
    mock_store,
    mock_keyword_store,
    mock_reranker,
    mock_pipeline,
    mock_log_port,
):
    """RETRIEVAL_MODE=hybrid: 向量 + BM25 并行召回 → RRF 融合 → rerank。"""
    mock_kb = use_case._kb_repo
    mock_kb.exists.return_value = True

    vec_hits = [
        _make_hit("c1", score=0.9),
        _make_hit("c2", score=0.8),
        _make_hit("c3", score=0.5),
    ]
    kw_hits = [_make_hit("c2", score=5.0), _make_hit("c4", score=3.0)]

    mock_store.search_by_vector.return_value = vec_hits
    mock_keyword_store.search_by_keyword.return_value = kw_hits

    # 重排 mock 记录收到的 chunks（应该是 RRF 融合后的 4 个去重 chunk）
    received_chunks = []

    async def _capture(*, query, query_vector, kb_ids, chunks, top_n):
        received_chunks.extend(chunks)
        return chunks[:top_n]

    mock_reranker.rerank.side_effect = _capture

    result = await use_case.execute(
        tenant_id="test-tenant", query="test query", kb_ids=["kb1"], top_k=3
    )

    # 验证：embedder 被调用两次文本（改写后 query + 原始 query）
    mock_embedder.embed.assert_awaited_once()
    call_args = mock_embedder.embed.await_args[0][0]
    assert len(call_args) == 2
    assert call_args[0] == "test query"  # rewrite passthrough → 改写后 = 原始
    assert call_args[1] == "test query"  # 原始 query

    # 验证：并行召回两路
    mock_store.search_by_vector.assert_awaited_once()
    mock_keyword_store.search_by_keyword.assert_awaited_once_with(
        "kb1", "test query", 20
    )

    # 验证：RRF 融合后 rerank 收到的 chunk 数 = 4（去重后 c1, c2, c3, c4）
    assert len(received_chunks) == 4
    chunk_ids = {h.chunk_id for h in received_chunks}
    assert chunk_ids == {"c1", "c2", "c3", "c4"}

    # 验证：rerank 用原始 query embedding（第二个向量）
    rerank_kwargs = mock_reranker.rerank.await_args.kwargs
    assert rerank_kwargs["query"] == "test query"
    assert rerank_kwargs["query_vector"] == [0.4, 0.5, 0.6]
    assert rerank_kwargs["top_n"] == 5  # 默认 rerank_top_n=5

    import asyncio

    await asyncio.sleep(0.01)  # yield to let the fire-and-forget task run
    # 验证：日志仍写入
    mock_log_port.log.assert_awaited_once()


@pytest.mark.asyncio
async def test_vector_only_mode(
    use_case,
    mock_embedder,
    mock_store,
    mock_keyword_store,
    mock_reranker,
):
    """RETRIEVAL_MODE=vector: 仅向量召回，BM25 不调用。"""
    use_case._retrieval_mode = "vector"

    mock_kb = use_case._kb_repo
    mock_kb.exists.return_value = True

    vec_hits = [_make_hit("c1"), _make_hit("c2"), _make_hit("c3")]
    mock_store.search_by_vector.return_value = vec_hits

    result = await use_case.execute(
        tenant_id="test-tenant", query="test query", kb_ids=["kb1"], top_k=2
    )

    # 验证：仅调用向量搜索
    mock_store.search_by_vector.assert_awaited_once()
    mock_keyword_store.search_by_keyword.assert_not_called()

    # 验证：rerank 收到向量召回结果（RRF 融合后 score 被重新计算）
    received_chunks = mock_reranker.rerank.await_args.kwargs["chunks"]
    assert len(received_chunks) == 3
    assert [h.chunk_id for h in received_chunks] == [h.chunk_id for h in vec_hits]

    assert len(result.hits) == 3  # rerank_top_n=5, 全部 3 条保留


@pytest.mark.asyncio
async def test_bm25_only_mode(
    use_case,
    mock_embedder,
    mock_store,
    mock_keyword_store,
    mock_reranker,
):
    """RETRIEVAL_MODE=bm25: 仅 BM25 召回，向量搜索不调用。"""
    use_case._retrieval_mode = "bm25"

    mock_kb = use_case._kb_repo
    mock_kb.exists.return_value = True

    kw_hits = [_make_hit("c1"), _make_hit("c2"), _make_hit("c3")]
    mock_keyword_store.search_by_keyword.return_value = kw_hits

    result = await use_case.execute(
        tenant_id="test-tenant", query="test query", kb_ids=["kb1"], top_k=2
    )

    # 验证：仅调用 keyword search
    mock_store.search_by_vector.assert_not_called()
    mock_keyword_store.search_by_keyword.assert_awaited_once_with(
        "kb1", "test query", 20
    )

    # 验证：rerank 收到 BM25 结果（RRF 融合后 score 被重新计算）
    received_chunks = mock_reranker.rerank.await_args.kwargs["chunks"]
    assert len(received_chunks) == 3
    assert [h.chunk_id for h in received_chunks] == [h.chunk_id for h in kw_hits]

    assert len(result.hits) == 3  # rerank_top_n=5, 全部 3 条保留


@pytest.mark.asyncio
async def test_keyword_fallback(
    use_case,
    mock_embedder,
    mock_store,
    mock_keyword_store,
    mock_reranker,
):
    """keyword search 失败时返回 []，不中断整体流程。"""
    mock_kb = use_case._kb_repo
    mock_kb.exists.return_value = True

    vec_hits = [_make_hit("c1"), _make_hit("c2"), _make_hit("c3")]
    mock_store.search_by_vector.return_value = vec_hits

    # BM25 抛出异常
    mock_keyword_store.search_by_keyword.side_effect = RuntimeError("ES 挂了")

    result = await use_case.execute(
        tenant_id="test-tenant", query="test query", kb_ids=["kb1"], top_k=2
    )

    # 验证：向量搜索正常完成
    mock_store.search_by_vector.assert_awaited_once()

    # 验证：RRF 融合时 kw_hits 为空列表，不崩溃
    # rerank 收到的应该是仅向量召回的结果
    received_chunks = mock_reranker.rerank.await_args.kwargs["chunks"]
    assert len(received_chunks) == 3

    assert len(result.hits) == 3  # rerank_top_n=5, 全部 3 条保留


@pytest.mark.asyncio
async def test_keyword_search_only_fallback(
    use_case,
    mock_embedder,
    mock_store,
    mock_keyword_store,
    mock_reranker,
):
    """bm25-only 模式下 keyword search 失败 → 返回空结果，不中断。"""
    use_case._retrieval_mode = "bm25"

    mock_kb = use_case._kb_repo
    mock_kb.exists.return_value = True

    mock_keyword_store.search_by_keyword.side_effect = RuntimeError("ES 挂了")

    result = await use_case.execute(
        tenant_id="test-tenant", query="test query", kb_ids=["kb1"], top_k=2
    )

    # 验证：无崩溃，返回空列表
    assert result.hits == []
