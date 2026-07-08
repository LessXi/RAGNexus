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


# ══════════════════════════════════════════════════════════════════════
# execute 方法测试 — per-KB 并行召回 + 跨库 RRF 融合
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_execute_per_kb_parallel_with_two_kbs(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_reranker,
):
    """多 KB (len=2) 走 per-KB 并行召回 → cross_kb_rrf_fuse 被调用。"""
    from unittest.mock import patch

    # 简化：禁用 rerank + 跳过 ownership 校验
    mock_reranker.model_name = None
    with patch.object(use_case, "validate_kb_ownership", new_callable=AsyncMock):
        mock_kb_repo.exists.return_value = True
        mock_embedder.embed.return_value = [[0.1] * 10, [0.2] * 10]

        # 单库召回结果
        hits_kb1 = [_make_hit("c1", "kb1", "d1", 0.9)]
        hits_kb2 = [_make_hit("c2", "kb2", "d2", 0.8)]

        with patch.object(
            use_case, "_retrieve_per_kb", new_callable=AsyncMock
        ) as mock_retrieve:
            mock_retrieve.side_effect = [hits_kb1, hits_kb2]

            with patch(
                "ragnexus.application.retrieve_use_case.cross_kb_rrf_fuse"
            ) as mock_fuse:
                fused = [
                    _make_hit("c1", "kb1", "d1", 1.0),
                    _make_hit("c2", "kb2", "d2", 0.8),
                ]
                mock_fuse.return_value = fused

                result = await use_case.execute(
                    query="test query",
                    kb_ids=["kb1", "kb2"],
                    tenant_id="tenant1",
                    top_k=5,
                )

    # 验证 _retrieve_per_kb 被调用了两次（每个 KB 一次）
    assert mock_retrieve.call_count == 2
    # 验证 per_kb_top_k 参数
    assert mock_retrieve.call_args_list[0][0][3] == 20  # max(5, 20, 20, 10) = 20

    # 验证 cross_kb_rrf_fuse 被调用
    mock_fuse.assert_called_once()
    args, kwargs = mock_fuse.call_args
    assert len(args[0]) == 2, "应传入两个 KB 的 hits 组"
    assert kwargs["k"] == 60

    # 验证结果
    assert result.total == 2
    assert len(result.hits) == 2


@pytest.mark.asyncio
async def test_execute_single_kb_uses_unified_path(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_reranker,
):
    """单 KB 也走 per-KB 新路径 + cross_kb_rrf_fuse（恒等映射）。"""
    from unittest.mock import patch

    mock_reranker.model_name = None
    with patch.object(use_case, "validate_kb_ownership", new_callable=AsyncMock):
        mock_kb_repo.exists.return_value = True
        mock_embedder.embed.return_value = [[0.1] * 10, [0.2] * 10]

        hits_kb1 = [
            _make_hit("c1", "kb1", "d1", 0.9),
            _make_hit("c2", "kb1", "d1", 0.8),
        ]

        with patch.object(
            use_case, "_retrieve_per_kb", new_callable=AsyncMock
        ) as mock_retrieve:
            mock_retrieve.return_value = hits_kb1

            with patch(
                "ragnexus.application.retrieve_use_case.cross_kb_rrf_fuse"
            ) as mock_fuse:
                mock_fuse.return_value = hits_kb1  # 恒等映射

                result = await use_case.execute(
                    query="test query",
                    kb_ids=["kb1"],
                    tenant_id="tenant1",
                    top_k=5,
                )

    # 验证 _retrieve_per_kb 被调用一次
    mock_retrieve.assert_called_once()

    # 验证 cross_kb_rrf_fuse 被调用（传入单组 hits）
    mock_fuse.assert_called_once()
    args, kwargs = mock_fuse.call_args
    assert len(args[0]) == 1, "单 KB 应传单组"
    assert args[0][0] == hits_kb1

    # 结果正确
    assert result.total == 2


@pytest.mark.asyncio
async def test_execute_kb_exception_not_blocking(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_reranker,
):
    """一个 KB 抛异常不阻塞其他 KB 的正常召回。"""
    from unittest.mock import patch

    mock_reranker.model_name = None
    with patch.object(use_case, "validate_kb_ownership", new_callable=AsyncMock):
        mock_kb_repo.exists.return_value = True
        mock_embedder.embed.return_value = [[0.1] * 10, [0.2] * 10]

        hits_kb2 = [_make_hit("c2", "kb2", "d2", 0.8)]

        with patch.object(
            use_case, "_retrieve_per_kb", new_callable=AsyncMock
        ) as mock_retrieve:
            # kb1 抛异常，kb2 正常返回
            mock_retrieve.side_effect = [RuntimeError("KB 故障"), hits_kb2]

            with patch(
                "ragnexus.application.retrieve_use_case.cross_kb_rrf_fuse"
            ) as mock_fuse:
                mock_fuse.return_value = hits_kb2

                result = await use_case.execute(
                    query="test query",
                    kb_ids=["kb1", "kb2"],
                    tenant_id="tenant1",
                    top_k=5,
                )

    # 验证 _retrieve_per_kb 仍被调用了两次
    assert mock_retrieve.call_count == 2

    # 验证 cross_kb_rrf_fuse 只收到正常 KB 的 hits
    mock_fuse.assert_called_once()
    args, kwargs = mock_fuse.call_args
    assert len(args[0]) == 1, "应只传入正常 KB 的 hits"

    # 结果正常返回
    assert result.total == 1
    assert result.hits[0].chunk_id == "c2"


@pytest.mark.asyncio
async def test_execute_uses_per_kb_top_k(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_reranker,
):
    """验证 per_kb_top_k = max(top_k, vector_top_k, bm25_top_k, 10)。"""
    from unittest.mock import patch

    mock_reranker.model_name = None
    with patch.object(use_case, "validate_kb_ownership", new_callable=AsyncMock):
        mock_kb_repo.exists.return_value = True
        mock_embedder.embed.return_value = [[0.1] * 10, [0.2] * 10]

        hits = [_make_hit("c1", "kb1", "d1", 0.9)]

        with patch.object(
            use_case, "_retrieve_per_kb", new_callable=AsyncMock
        ) as mock_retrieve:
            mock_retrieve.return_value = hits

            with patch(
                "ragnexus.application.retrieve_use_case.cross_kb_rrf_fuse"
            ) as mock_fuse:

                # top_k=3, vector_top_k=20, bm25_top_k=15 → per_kb_top_k = max(3,20,15,10)=20
                await use_case.execute(
                    query="test query",
                    kb_ids=["kb1"],
                    tenant_id="tenant1",
                    top_k=3,
                    vector_top_k=20,
                    bm25_top_k=15,
                )

    # 验证传给 _retrieve_per_kb 的 per_kb_top_k = 20
    assert mock_retrieve.call_args[0][3] == 20, "应为 max(3, 20, 15, 10) = 20"
