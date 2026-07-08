"""RetrieveUseCase._retrieve_per_kb 单元测试 — 单库双路召回 + 降级策略。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ragnexus.application.retrieve_use_case import RetrieveUseCase
from ragnexus.domain.models import SearchHit


# ── 工厂函数 ──────────────────────────────────────────────────────────
def _make_hit(
    chunk_id: str,
    kb_id: str = "kb_test",
    doc_id: str = "",
    score: float = 0.9,
    text: str = "",
    metadata: dict | None = None,
) -> SearchHit:
    """创建测试用 SearchHit。"""
    return SearchHit(
        chunk_id=chunk_id,
        kb_id=kb_id,
        doc_id=doc_id,
        score=score,
        text=text,
        metadata=metadata or {},
    )


# ── Fixtures ──────────────────────────────────────────────────────────
@pytest.fixture
def mock_store():
    """模拟 VectorStorePort。"""
    return AsyncMock()


@pytest.fixture
def mock_keyword_store():
    """模拟 KeywordSearchPort。"""
    return AsyncMock()


@pytest.fixture
def mock_kb_repo():
    """模拟 KnowledgeBasePort。"""
    return AsyncMock()


@pytest.fixture
def mock_embedder():
    """模拟 EmbedderPort。"""
    return AsyncMock()


@pytest.fixture
def mock_log_port():
    """模拟 RetrieveLogPort。"""
    return AsyncMock()


@pytest.fixture
def mock_reranker():
    """模拟 RerankPort。"""
    return AsyncMock()


@pytest.fixture
def mock_pipeline():
    """模拟 QueryPipeline。"""
    m = AsyncMock()
    from ragnexus.domain.ports import QueryProcessResult

    m.process.return_value = QueryProcessResult(
        raw_query="test query",
        effective_query="test query",
        search_query="test query",
        needs_rewrite=False,
        strategy="noop",
        rewrite_latency_ms=0,
        degraded=False,
        degraded_reason=None,
        synonym_applied=False,
        synonym_expansions=[],
    )
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
    """构造 RetrieveUseCase 实例，注入模拟端口。"""
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


# ── 测试用例 ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_retrieve_per_kb_returns_rank_ordered_hits(
    use_case, mock_store, mock_keyword_store
):
    """双路召回 → RRF 融合后按 score 降序排列。"""
    # 准备：向量检索返回 3 条
    vec_hits = [
        _make_hit("c1", kb_id="kb_a", score=0.95, text="high vec"),
        _make_hit("c2", kb_id="kb_a", score=0.85, text="mid vec"),
        _make_hit("c3", kb_id="kb_a", score=0.75, text="low vec"),
    ]
    # BM25 返回 3 条（不同 rank 顺序，c3 在 BM25 排第一）
    kw_hits = [
        _make_hit("c3", kb_id="kb_a", score=2.5, text="low vec"),
        _make_hit("c4", kb_id="kb_a", score=2.0, text="bm25 only"),
        _make_hit("c1", kb_id="kb_a", score=1.5, text="high vec"),
    ]

    mock_store.search_by_vector.return_value = vec_hits
    mock_keyword_store.search_by_keyword.return_value = kw_hits

    search_vector = [0.1, 0.2, 0.3]

    result = await use_case._retrieve_per_kb(
        kb_id="kb_a",
        search_vector=search_vector,
        original_query="test query",
        per_kb_top_k=5,
        rrf_k=60,
        use_vector=True,
        use_bm25=True,
    )

    # 验证：结果非空
    assert len(result) > 0, "应该返回融合后的结果"
    # 验证：score 降序
    for i in range(len(result) - 1):
        assert (
            result[i].score >= result[i + 1].score
        ), f"结果应按 RRF score 降序排列，但 {result[i].score} < {result[i + 1].score}"
    # 验证：重叠 chunk（c1, c3）的 score 应 > 单路 chunk（c2, c4）
    c1_score = next(h.score for h in result if h.chunk_id == "c1")
    c3_score = next(h.score for h in result if h.chunk_id == "c3")
    c2_score = next(h.score for h in result if h.chunk_id == "c2")
    c4_score = next(h.score for h in result if h.chunk_id == "c4")
    assert c1_score > c2_score, "重叠 chunk c1 的 RRF 分应高于纯向量 c2"
    assert c3_score > c4_score, "重叠 chunk c3 的 RRF 分应高于纯 BM25 c4"


@pytest.mark.asyncio
async def test_retrieve_per_kb_bm25_empty_falls_back_to_vector(
    use_case, mock_store, mock_keyword_store
):
    """BM25 返回 [] → 降级为纯向量结果。"""
    vec_hits = [
        _make_hit("c1", kb_id="kb_a", score=0.95, text="vec only 1"),
        _make_hit("c2", kb_id="kb_a", score=0.85, text="vec only 2"),
    ]

    mock_store.search_by_vector.return_value = vec_hits
    mock_keyword_store.search_by_keyword.return_value = []

    search_vector = [0.1, 0.2, 0.3]

    result = await use_case._retrieve_per_kb(
        kb_id="kb_a",
        search_vector=search_vector,
        original_query="test query",
        per_kb_top_k=5,
        rrf_k=60,
        use_vector=True,
        use_bm25=True,
    )

    # 验证：结果包含所有向量 hits
    assert len(result) == 2, f"纯向量降级应返回 2 条结果，实际 {len(result)}"
    chunk_ids = {h.chunk_id for h in result}
    assert chunk_ids == {"c1", "c2"}, f"应包含所有向量 hits，实际 {chunk_ids}"
    # 验证：降序排列
    assert result[0].score >= result[1].score


@pytest.mark.asyncio
async def test_retrieve_per_kb_vector_empty_falls_back_to_bm25(
    use_case, mock_store, mock_keyword_store
):
    """向量检索返回 [] → 降级为纯 BM25 结果。"""
    kw_hits = [
        _make_hit("c1", kb_id="kb_a", score=2.5, text="bm25 only 1"),
        _make_hit("c2", kb_id="kb_a", score=2.0, text="bm25 only 2"),
    ]

    mock_store.search_by_vector.return_value = []
    mock_keyword_store.search_by_keyword.return_value = kw_hits

    search_vector = [0.1, 0.2, 0.3]

    result = await use_case._retrieve_per_kb(
        kb_id="kb_a",
        search_vector=search_vector,
        original_query="test query",
        per_kb_top_k=5,
        rrf_k=60,
        use_vector=True,
        use_bm25=True,
    )

    # 验证：结果包含所有 BM25 hits
    assert len(result) == 2, f"纯 BM25 降级应返回 2 条结果，实际 {len(result)}"
    chunk_ids = {h.chunk_id for h in result}
    assert chunk_ids == {"c1", "c2"}, f"应包含所有 BM25 hits，实际 {chunk_ids}"
    # 验证：降序排列
    assert result[0].score >= result[1].score


@pytest.mark.asyncio
async def test_retrieve_per_kb_both_empty_returns_empty(
    use_case, mock_store, mock_keyword_store
):
    """两路都失败 → 返回空列表。"""
    mock_store.search_by_vector.return_value = []
    mock_keyword_store.search_by_keyword.return_value = []

    search_vector = [0.1, 0.2, 0.3]

    result = await use_case._retrieve_per_kb(
        kb_id="kb_a",
        search_vector=search_vector,
        original_query="test query",
        per_kb_top_k=5,
        rrf_k=60,
        use_vector=True,
        use_bm25=True,
    )

    assert result == [], "两路失败应返回空列表"
    # 验证：两路都确实被调用了
    mock_store.search_by_vector.assert_awaited_once()
    mock_keyword_store.search_by_keyword.assert_awaited_once()
