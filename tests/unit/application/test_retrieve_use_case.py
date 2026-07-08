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
    m = AsyncMock()
    m.get.return_value = None
    return m


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

    hits, vec_count, kw_count = await use_case._retrieve_per_kb(
        kb_id="kb_a",
        search_vector=search_vector,
        original_query="test query",
        per_kb_top_k=5,
        rrf_k=60,
        use_vector=True,
        use_bm25=True,
    )

    # 验证：结果非空
    assert len(hits) > 0, "应该返回融合后的结果"
    # 验证：score 降序
    for i in range(len(hits) - 1):
        assert (
            hits[i].score >= hits[i + 1].score
        ), f"结果应按 RRF score 降序排列，但 {hits[i].score} < {hits[i + 1].score}"
    # 验证：重叠 chunk（c1, c3）的 score 应 > 单路 chunk（c2, c4）
    c1_score = next(h.score for h in hits if h.chunk_id == "c1")
    c3_score = next(h.score for h in hits if h.chunk_id == "c3")
    c2_score = next(h.score for h in hits if h.chunk_id == "c2")
    c4_score = next(h.score for h in hits if h.chunk_id == "c4")
    assert c1_score > c2_score, "重叠 chunk c1 的 RRF 分应高于纯向量 c2"
    assert c3_score > c4_score, "重叠 chunk c3 的 RRF 分应高于纯 BM25 c4"
    # 验证计数
    assert vec_count == 3, f"vector_count 应为 3，实际 {vec_count}"
    assert kw_count == 3, f"bm25_count 应为 3，实际 {kw_count}"


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
    hits, vec_count, kw_count = await use_case._retrieve_per_kb(
        kb_id="kb_a",
        search_vector=search_vector,
        original_query="test query",
        per_kb_top_k=5,
        rrf_k=60,
        use_vector=True,
        use_bm25=True,
    )

    # 验证：结果包含所有向量 hits
    assert len(hits) == 2, f"纯向量降级应返回 2 条结果，实际 {len(hits)}"
    chunk_ids = {h.chunk_id for h in hits}
    assert chunk_ids == {"c1", "c2"}, f"应包含所有向量 hits，实际 {chunk_ids}"
    # 验证：降序排列
    assert hits[0].score >= hits[1].score
    # 验证计数
    assert vec_count == 2, f"vector_count 应为 2，实际 {vec_count}"
    assert kw_count == 0, f"bm25_count 应为 0（BM25 为空），实际 {kw_count}"


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
    hits, vec_count, kw_count = await use_case._retrieve_per_kb(
        kb_id="kb_a",
        search_vector=search_vector,
        original_query="test query",
        per_kb_top_k=5,
        rrf_k=60,
        use_vector=True,
        use_bm25=True,
    )

    # 验证：结果包含所有 BM25 hits
    assert len(hits) == 2, f"纯 BM25 降级应返回 2 条结果，实际 {len(hits)}"
    chunk_ids = {h.chunk_id for h in hits}
    assert chunk_ids == {"c1", "c2"}, f"应包含所有 BM25 hits，实际 {chunk_ids}"
    # 验证：降序排列
    assert hits[0].score >= hits[1].score
    # 验证计数
    assert vec_count == 0, f"vector_count 应为 0（向量为空），实际 {vec_count}"
    assert kw_count == 2, f"bm25_count 应为 2，实际 {kw_count}"


@pytest.mark.asyncio
async def test_retrieve_per_kb_both_empty_returns_empty(
    use_case, mock_store, mock_keyword_store
):
    """两路都失败 → 返回空列表。"""
    mock_store.search_by_vector.return_value = []
    mock_keyword_store.search_by_keyword.return_value = []
    search_vector = [0.1, 0.2, 0.3]
    hits, vec_count, kw_count = await use_case._retrieve_per_kb(
        kb_id="kb_a",
        search_vector=search_vector,
        original_query="test query",
        per_kb_top_k=5,
        rrf_k=60,
        use_vector=True,
        use_bm25=True,
    )

    assert hits == [], "两路失败应返回空列表"
    assert vec_count == 0, "vector_count 应为 0"
    assert kw_count == 0, "bm25_count 应为 0"
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
            # 返回三元组 (hits, vector_count, bm25_count)
            mock_retrieve.side_effect = [(hits_kb1, 2, 2), (hits_kb2, 1, 1)]

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
    # 验证向量/BM25 计数已聚合
    assert (
        result.vector_count == 3
    ), f"vector_count 应为 2+1=3，实际 {result.vector_count}"
    assert result.bm25_count == 3, f"bm25_count 应为 2+1=3，实际 {result.bm25_count}"
    # 验证无降级 KB
    assert result.degraded_kb_ids == []


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
            mock_retrieve.return_value = (hits_kb1, 3, 2)

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
    assert result.vector_count == 3
    assert result.bm25_count == 2


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
            # kb1 抛异常，kb2 正常返回三元组
            mock_retrieve.side_effect = [RuntimeError("KB 故障"), (hits_kb2, 1, 1)]

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
    # 验证降级 KB 记录
    assert "kb1" in result.degraded_kb_ids


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
            mock_retrieve.return_value = (hits, 1, 1)

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


# ══════════════════════════════════════════════════════════════════════
# Task 1.5 测试 — kb_name 预加载与填充
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_kb_name_populated(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_reranker,
):
    """跨库 RRF 融合后 hit.kb_name 从 DB 批量填充。"""
    from unittest.mock import patch

    mock_reranker.model_name = None
    with patch.object(use_case, "validate_kb_ownership", new_callable=AsyncMock):
        mock_kb_repo.exists.return_value = True
        mock_embedder.embed.return_value = [[0.1] * 10, [0.2] * 10]

        # 模拟 pool.fetch 返回 kb_id → name 映射
        mock_kb_repo.pool.fetch.return_value = [
            {"id": "kb1", "name": "知识库 Alpha"},
            {"id": "kb2", "name": "知识库 Beta"},
            {"id": "kb3", "name": "知识库 Gamma"},
        ]

        hits_kb1 = [_make_hit("c1", "kb1", "d1", 0.9)]
        hits_kb2 = [_make_hit("c2", "kb2", "d2", 0.8)]
        hits_kb3 = [_make_hit("c3", "kb3", "d3", 0.7)]

        with patch.object(
            use_case, "_retrieve_per_kb", new_callable=AsyncMock
        ) as mock_retrieve:
            mock_retrieve.side_effect = [
                (hits_kb1, 1, 1),
                (hits_kb2, 1, 1),
                (hits_kb3, 1, 1),
            ]

            with patch(
                "ragnexus.application.retrieve_use_case.cross_kb_rrf_fuse"
            ) as mock_fuse:
                fused = [
                    _make_hit("c1", "kb1", "d1", 1.0),
                    _make_hit("c2", "kb2", "d2", 0.8),
                    _make_hit("c3", "kb3", "d3", 0.6),
                ]
                mock_fuse.return_value = fused

                result = await use_case.execute(
                    query="test query",
                    kb_ids=["kb1", "kb2", "kb3"],
                    tenant_id="tenant1",
                    top_k=5,
                )

    # 验证 pool.fetch 被调用（查询所有 kb_ids）
    mock_kb_repo.pool.fetch.assert_awaited_once()
    call_args = mock_kb_repo.pool.fetch.call_args
    assert "SELECT id, name FROM knowledge_bases" in call_args[0][0]

    # 验证 kb_name 正确填充
    assert result.total == 3
    kb_names = {hit.kb_id: hit.kb_name for hit in result.hits}
    assert (
        kb_names["kb1"] == "知识库 Alpha"
    ), f"kb1 name 应为 '知识库 Alpha'，实际: {kb_names['kb1']}"
    assert (
        kb_names["kb2"] == "知识库 Beta"
    ), f"kb2 name 应为 '知识库 Beta'，实际: {kb_names['kb2']}"
    assert (
        kb_names["kb3"] == "知识库 Gamma"
    ), f"kb3 name 应为 '知识库 Gamma'，实际: {kb_names['kb3']}"


@pytest.mark.asyncio
async def test_kb_name_fallback(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_reranker,
):
    """DB 中不存在 kb_id → kb_name 回退为 kb_id[:8]。"""
    from unittest.mock import patch

    mock_reranker.model_name = None
    with patch.object(use_case, "validate_kb_ownership", new_callable=AsyncMock):
        mock_kb_repo.exists.return_value = True
        mock_embedder.embed.return_value = [[0.1] * 10, [0.2] * 10]

        # pool.fetch 只返回 kb1，不包含 kb_unknown
        mock_kb_repo.pool.fetch.return_value = [
            {"id": "kb1", "name": "知识库 Alpha"},
        ]

        hits_kb1 = [_make_hit("c1", "kb1", "d1", 0.9)]
        hits_unknown = [_make_hit("c_unk", "kb_unknown", "d_unk", 0.7)]

        with patch.object(
            use_case, "_retrieve_per_kb", new_callable=AsyncMock
        ) as mock_retrieve:
            mock_retrieve.side_effect = [
                (hits_kb1, 1, 1),
                (hits_unknown, 1, 1),
            ]

            with patch(
                "ragnexus.application.retrieve_use_case.cross_kb_rrf_fuse"
            ) as mock_fuse:
                fused = [
                    _make_hit("c1", "kb1", "d1", 1.0),
                    _make_hit("c_unk", "kb_unknown", "d_unk", 0.6),
                ]
                mock_fuse.return_value = fused

                result = await use_case.execute(
                    query="test query",
                    kb_ids=["kb1", "kb_unknown"],
                    tenant_id="tenant1",
                    top_k=5,
                )

    # kb1 → 从 DB 填充
    # kb_unknown → 回退为 kb_id[:8]
    kb_names = {hit.kb_id: hit.kb_name for hit in result.hits}
    assert (
        kb_names["kb1"] == "知识库 Alpha"
    ), f"kb1 name 应为 '知识库 Alpha'，实际: {kb_names['kb1']}"
    assert (
        kb_names["kb_unknown"] == "kb_unkno"
    ), f"kb_unknown name 应为 'kb_unkno' (kb_id[:8])，实际: {kb_names['kb_unknown']}"


# ══════════════════════════════════════════════════════════════════════
# Batch 1 修复测试 — vector/bm25 counts, degraded_kb_ids, per-pathway 异常
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_retrieve_per_kb_returns_vector_and_bm25_counts(
    use_case, mock_store, mock_keyword_store
):
    """_retrieve_per_kb 返回三元组 (hits, vector_count, bm25_count)。"""
    vec_hits = [_make_hit("c1", "kb1", "d1", 0.9, "vec text")]
    kw_hits = [_make_hit("c2", "kb1", "d1", 0.7, "kw text")]
    mock_store.search_by_vector.return_value = vec_hits
    mock_keyword_store.search_by_keyword.return_value = kw_hits

    result = await use_case._retrieve_per_kb(
        kb_id="kb1",
        search_vector=[0.1] * 10,
        original_query="测试",
        per_kb_top_k=20,
        rrf_k=60,
        use_vector=True,
        use_bm25=True,
    )

    # 验证返回三元组
    hits, vec_count, kw_count = result
    assert isinstance(hits, list), "第一个元素应为 hits 列表"
    assert isinstance(vec_count, int), "第二个元素应为 vector_count (int)"
    assert isinstance(kw_count, int), "第三个元素应为 bm25_count (int)"
    assert vec_count == 1, "vector_count 应为 1"
    assert kw_count == 1, "bm25_count 应为 1"
    assert len(hits) > 0, "融合后 hits 不应为空"


@pytest.mark.asyncio
async def test_retrieve_per_kb_counts_zero_when_disabled(
    use_case, mock_store, mock_keyword_store
):
    """use_vector=False 时 vector_count 应为 0，use_bm25=False 时 bm25_count 应为 0。"""
    kw_hits = [_make_hit("c1", "kb1", "d1", 0.9, "kw only")]
    mock_keyword_store.search_by_keyword.return_value = kw_hits

    # 仅 BM25 模式
    result = await use_case._retrieve_per_kb(
        kb_id="kb1",
        search_vector=[0.1] * 10,
        original_query="测试",
        per_kb_top_k=20,
        rrf_k=60,
        use_vector=False,
        use_bm25=True,
    )
    hits, vec_count, kw_count = result
    assert vec_count == 0, "use_vector=False 时 vector_count 应为 0"
    assert kw_count == 1, "bm25_count 应为 1"


@pytest.mark.asyncio
async def test_execute_aggregates_vector_bm25_counts(
    use_case, mock_kb_repo, mock_embedder, mock_reranker
):
    """execute 聚合所有 per-KB 的 vector/bm25 计数到 RetrieveResult。"""
    from unittest.mock import patch

    mock_reranker.model_name = None
    with patch.object(use_case, "validate_kb_ownership", new_callable=AsyncMock):
        mock_kb_repo.exists.return_value = True
        mock_embedder.embed.return_value = [[0.1] * 10, [0.2] * 10]

        # 模拟 _retrieve_per_kb 返回三元组
        # KB1: 3 vector hits, 2 BM25 hits → fused into 4 hits
        fused1 = [
            _make_hit("c1", "kb1", "d1", 0.9),
            _make_hit("c2", "kb1", "d1", 0.8),
            _make_hit("c3", "kb1", "d1", 0.7),
            _make_hit("c4", "kb1", "d1", 0.6),
        ]
        # KB2: 1 vector hit, 1 BM25 hit → fused into 2 hits
        fused2 = [
            _make_hit("c5", "kb2", "d5", 0.85),
            _make_hit("c6", "kb2", "d5", 0.75),
        ]

        with patch.object(
            use_case, "_retrieve_per_kb", new_callable=AsyncMock
        ) as mock_retrieve:
            mock_retrieve.side_effect = [
                (fused1, 3, 2),  # KB1: 3 vector, 2 BM25
                (fused2, 1, 1),  # KB2: 1 vector, 1 BM25
            ]

            with patch(
                "ragnexus.application.retrieve_use_case.cross_kb_rrf_fuse"
            ) as mock_fuse:
                mock_fuse.return_value = fused1 + fused2

                result = await use_case.execute(
                    query="test query",
                    kb_ids=["kb1", "kb2"],
                    tenant_id="tenant1",
                    top_k=10,
                )

    # 聚合后：vector_count = 3+1 = 4, bm25_count = 2+1 = 3
    assert result.vector_count == 4, f"vector_count 应为 4，实际: {result.vector_count}"
    assert result.bm25_count == 3, f"bm25_count 应为 3，实际: {result.bm25_count}"


@pytest.mark.asyncio
async def test_execute_surfaces_degraded_kb_ids(
    use_case, mock_kb_repo, mock_embedder, mock_reranker
):
    """异常的 KB 将 degraded_kb_ids 记录到 RetrieveResult。"""
    from unittest.mock import patch

    mock_reranker.model_name = None
    with patch.object(use_case, "validate_kb_ownership", new_callable=AsyncMock):
        mock_kb_repo.exists.return_value = True
        mock_embedder.embed.return_value = [[0.1] * 10, [0.2] * 10]

        hits_kb2 = [_make_hit("c2", "kb2", "d2", 0.8)]

        with patch.object(
            use_case, "_retrieve_per_kb", new_callable=AsyncMock
        ) as mock_retrieve:
            # kb1 抛异常 → degraded，kb2 正常
            mock_retrieve.side_effect = [RuntimeError("KB 故障"), ([], 0, 0)]

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

    assert "kb1" in result.degraded_kb_ids, "异常的 KB 应出现在 degraded_kb_ids 中"


@pytest.mark.asyncio
async def test_retrieve_per_kb_catches_per_pathway_exception(
    use_case, mock_store, mock_keyword_store
):
    """vector 检索抛异常 → 不中断 BM25 检索，降级为纯 BM25。"""
    # 向量检索抛异常
    mock_store.search_by_vector.side_effect = RuntimeError("向量库连接失败")
    # BM25 正常返回
    kw_hits = [_make_hit("c1", "kb1", "d1", 0.7, "keyword result")]
    mock_keyword_store.search_by_keyword.return_value = kw_hits

    # 不应抛异常
    result = await use_case._retrieve_per_kb(
        kb_id="kb1",
        search_vector=[0.1] * 10,
        original_query="测试",
        per_kb_top_k=20,
        rrf_k=60,
        use_vector=True,
        use_bm25=True,
    )

    hits, vec_count, kw_count = result
    # vector 检索异常，应降级：vec_count=0，但 BM25 仍有结果
    assert vec_count == 0, "向量检索异常时 vector_count 应为 0"
    assert kw_count == 1, "BM25 检索应正常返回 1 条"
    assert len(hits) > 0, "降级后仍有 BM25 融合结果"

    # 验证两个 search 都被调用
    mock_store.search_by_vector.assert_awaited_once()
    mock_keyword_store.search_by_keyword.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_per_kb_catches_both_pathway_exceptions(
    use_case, mock_store, mock_keyword_store
):
    """两路都抛异常 → 返回空三元组，不传播异常。"""
    mock_store.search_by_vector.side_effect = RuntimeError("向量库故障")
    mock_keyword_store.search_by_keyword.side_effect = RuntimeError("ES 故障")

    result = await use_case._retrieve_per_kb(
        kb_id="kb1",
        search_vector=[0.1] * 10,
        original_query="测试",
        per_kb_top_k=20,
        rrf_k=60,
        use_vector=True,
        use_bm25=True,
    )

    hits, vec_count, kw_count = result
    assert vec_count == 0
    assert kw_count == 0
    assert hits == [], "两路都异常时 hits 应为空"


# ══════════════════════════════════════════════════════════════════════
# Task 1.7 测试 — 多库 synonyms 合并去重
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_multi_kb_synonyms_merged(
    use_case,
    mock_kb_repo,
    mock_embedder,
    mock_reranker,
    mock_pipeline,
):
    """多 KB settings.synonyms 合并去重后传给 QueryPipeline.process。"""
    from datetime import datetime
    from unittest.mock import patch

    from ragnexus.domain.models import KnowledgeBase

    dt = datetime(2025, 1, 1)
    kb1 = KnowledgeBase(
        id="kb1",
        name="KB-A",
        created_at=dt,
        tenant_id="t1",
        settings={
            "synonyms": [
                {"term": "手机", "expansion": ["智能手机"]},
                {"term": "电脑", "expansion": ["计算机"]},
            ]
        },
    )
    kb2 = KnowledgeBase(
        id="kb2",
        name="KB-B",
        created_at=dt,
        tenant_id="t1",
        settings={
            "synonyms": [
                {"term": "手机", "expansion": ["移动电话"]},  # 与 kb1 term 重复
                {"term": "平板", "expansion": ["iPad"]},
            ]
        },
    )
    kb3 = KnowledgeBase(
        id="kb3",
        name="KB-C",
        created_at=dt,
        tenant_id="t1",
    )  # settings 为默认空 dict

    mock_reranker.model_name = None
    mock_kb_repo.exists.return_value = True
    # get 调用序列: primary(kb1) + loop(kb1, kb2, kb3) = 4 次
    mock_kb_repo.get.side_effect = [kb1, kb1, kb2, kb3]
    mock_embedder.embed.return_value = [[0.1] * 10, [0.2] * 10]

    with patch.object(use_case, "validate_kb_ownership", new_callable=AsyncMock):
        with patch.object(
            use_case, "_retrieve_per_kb", new_callable=AsyncMock
        ) as mock_retrieve:
            mock_retrieve.return_value = ([], 0, 0)

            await use_case.execute(
                query="test query",
                kb_ids=["kb1", "kb2", "kb3"],
                tenant_id="t1",
                top_k=5,
            )

    # 验证 pipeline.process 收到的 synonyms 参数
    mock_pipeline.process.assert_awaited_once()
    synonyms = mock_pipeline.process.call_args.kwargs["synonyms"]
    assert synonyms is not None
    assert isinstance(synonyms, list)

    # 按 term 去重：3 个唯一 term（手机 去重为 kb2 版本）
    assert len(synonyms) == 3, f"应去重为 3 条，实际 {len(synonyms)}"
    terms = {s["term"] for s in synonyms}
    assert terms == {"手机", "电脑", "平板"}, f"合并后的 terms: {terms}"

    # "手机" 保留后出现的 kb2 版本（dict 覆盖语义）
    phone = next(s for s in synonyms if s["term"] == "手机")
    assert phone["expansion"] == ["移动电话"], f"手机应来自 kb2，实际: {phone}"
