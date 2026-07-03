"""rrf_fuse 函数单元测试 — RRF (Reciprocal Rank Fusion) 融合算法。

验证两路检索结果的分数重算、去重合并与排序行为。
"""

from __future__ import annotations

import pytest

from ragnexus.domain.models import SearchHit


def _make_hit(chunk_id: str, score: float = 0.9) -> SearchHit:
    """创建测试用 SearchHit 的工厂函数。"""
    return SearchHit(
        chunk_id=chunk_id,
        kb_id="kb_test",
        doc_id=f"doc_{chunk_id}",
        score=score,
        text=f"content of {chunk_id}",
        metadata={},
    )


class TestRRFFuseNormal:
    """两路正常融合 — 均有结果，无重叠 chunk_id。"""

    def test_returns_all_unique_chunks(self) -> None:
        """融合后应包含两路的所有不重复 chunk。"""
        from ragnexus.domain.retrieval.fusion import rrf_fuse

        vector_hits = [
            _make_hit("chunk_a"),
            _make_hit("chunk_b"),
            _make_hit("chunk_c"),
        ]
        kw_hits = [
            _make_hit("chunk_d"),
            _make_hit("chunk_e"),
        ]

        result = rrf_fuse(vector_hits, kw_hits, k=60)

        chunk_ids = {h.chunk_id for h in result}
        assert chunk_ids == {"chunk_a", "chunk_b", "chunk_c", "chunk_d", "chunk_e"}
        assert len(result) == 5

    def test_rrf_scores_are_correct(self) -> None:
        """每个 chunk 的 RRF score 应等于 1/(k + rank)。

        vector: [chunk_a(r1), chunk_b(r2), chunk_c(r3)]
        keyword: [chunk_d(r1), chunk_e(r2)]
        """
        from ragnexus.domain.retrieval.fusion import rrf_fuse

        vector_hits = [
            _make_hit("chunk_a"),
            _make_hit("chunk_b"),
            _make_hit("chunk_c"),
        ]
        kw_hits = [
            _make_hit("chunk_d"),
            _make_hit("chunk_e"),
        ]

        result = rrf_fuse(vector_hits, kw_hits, k=60)

        scores = {h.chunk_id: h.score for h in result}

        k = 60
        assert scores["chunk_a"] == pytest.approx(1 / (k + 1))
        assert scores["chunk_b"] == pytest.approx(1 / (k + 2))
        assert scores["chunk_c"] == pytest.approx(1 / (k + 3))
        assert scores["chunk_d"] == pytest.approx(1 / (k + 1))
        assert scores["chunk_e"] == pytest.approx(1 / (k + 2))


class TestRRFFuseEmptyOneSide:
    """一路为空 — 只返回非空路的结果，scores 重算为 RRF。"""

    def test_empty_keyword_returns_vector_with_rrf_scores(self) -> None:
        """keyword_hits=[] 时，返回 vector_hits 且 scores 为 RRF 分数。"""
        from ragnexus.domain.retrieval.fusion import rrf_fuse

        vector_hits = [
            _make_hit("chunk_a", score=0.95),
            _make_hit("chunk_b", score=0.80),
            _make_hit("chunk_c", score=0.70),
        ]

        result = rrf_fuse(vector_hits, [], k=60)

        assert len(result) == 3
        scores = {h.chunk_id: h.score for h in result}
        k = 60
        assert scores["chunk_a"] == pytest.approx(1 / (k + 1))
        assert scores["chunk_b"] == pytest.approx(1 / (k + 2))
        assert scores["chunk_c"] == pytest.approx(1 / (k + 3))

    def test_empty_vector_returns_keyword_with_rrf_scores(self) -> None:
        """vector_hits=[] 时，返回 keyword_hits 且 scores 为 RRF 分数。"""
        from ragnexus.domain.retrieval.fusion import rrf_fuse

        kw_hits = [
            _make_hit("chunk_x", score=0.88),
            _make_hit("chunk_y", score=0.77),
        ]

        result = rrf_fuse([], kw_hits, k=60)

        assert len(result) == 2
        scores = {h.chunk_id: h.score for h in result}
        k = 60
        assert scores["chunk_x"] == pytest.approx(1 / (k + 1))
        assert scores["chunk_y"] == pytest.approx(1 / (k + 2))


class TestRRFFuseDedup:
    """跨来源去重 — 同一 chunk_id 在两路中均出现。"""

    def test_shared_chunk_merged_with_summed_score(self) -> None:
        """共享 chunk 的 RRF score 应为两路贡献之和。

        vector: [chunk_a(r1), chunk_shared(r2)]
        keyword: [chunk_shared(r1), chunk_b(r2)]

        chunk_shared = 1/(k+2) + 1/(k+1) > 单独任何一路
        """
        from ragnexus.domain.retrieval.fusion import rrf_fuse

        vector_hits = [
            _make_hit("chunk_a"),
            _make_hit("chunk_shared"),
        ]
        kw_hits = [
            _make_hit("chunk_shared"),
            _make_hit("chunk_b"),
        ]

        result = rrf_fuse(vector_hits, kw_hits, k=60)

        assert len(result) == 3  # chunk_a, chunk_shared, chunk_b

        scores = {h.chunk_id: h.score for h in result}
        k = 60

        # chunk_shared: 来自 vector rank2 + keyword rank1
        expected_shared = 1 / (k + 2) + 1 / (k + 1)
        assert scores["chunk_shared"] == pytest.approx(expected_shared)

        # chunk_a: 仅来自 vector rank1
        assert scores["chunk_a"] == pytest.approx(1 / (k + 1))

        # chunk_b: 仅来自 keyword rank2
        assert scores["chunk_b"] == pytest.approx(1 / (k + 2))

    def test_dedup_preserves_highest_rank_contribution(self) -> None:
        """去重后的合并分应反映 chunk 在各路中的最佳排名。

        vector: [chunk_x(r1), chunk_y(r2), chunk_z(r3)]
        keyword: [chunk_y(r1), chunk_w(r2)]

        chunk_y 在 keyword 中排名更高(r1)，合并分应包含此贡献。
        """
        from ragnexus.domain.retrieval.fusion import rrf_fuse

        vector_hits = [
            _make_hit("chunk_x"),
            _make_hit("chunk_y"),
            _make_hit("chunk_z"),
        ]
        kw_hits = [
            _make_hit("chunk_y"),
            _make_hit("chunk_w"),
        ]

        result = rrf_fuse(vector_hits, kw_hits, k=60)

        scores = {h.chunk_id: h.score for h in result}
        k = 60

        assert scores["chunk_y"] == pytest.approx(1 / (k + 2) + 1 / (k + 1))
        assert scores["chunk_x"] == pytest.approx(1 / (k + 1))
        assert scores["chunk_w"] == pytest.approx(1 / (k + 2))
        assert scores["chunk_z"] == pytest.approx(1 / (k + 3))


class TestRRFFuseOrdering:
    """排序验证 — 结果应按 RRF score 降序排列。"""

    def test_results_sorted_descending_by_rrf_score(self) -> None:
        """所有 score 互不相同时，顺序应严格降序。

        vector: [chunk_a(r1), chunk_b(r2), chunk_c(r3)]
        keyword: [chunk_b(r1), chunk_d(r2)]

        RRF scores (k=60):
          chunk_b = 1/61 + 1/62 ≈ 0.03227  (最高)
          chunk_a = 1/61 ≈ 0.01639
          chunk_d = 1/62 ≈ 0.01613
          chunk_c = 1/63 ≈ 0.01587
        """
        from ragnexus.domain.retrieval.fusion import rrf_fuse

        vector_hits = [
            _make_hit("chunk_a"),
            _make_hit("chunk_b"),
            _make_hit("chunk_c"),
        ]
        kw_hits = [
            _make_hit("chunk_b"),
            _make_hit("chunk_d"),
        ]

        result = rrf_fuse(vector_hits, kw_hits, k=60)

        ordered_ids = [h.chunk_id for h in result]
        assert ordered_ids == [
            "chunk_b",
            "chunk_a",
            "chunk_d",
            "chunk_c",
        ], f"期望 [chunk_b, chunk_a, chunk_d, chunk_c]，实际: {ordered_ids}"

    def test_scores_strictly_descending(self) -> None:
        """验证相邻 score 严格递减（无平局）。"""
        from ragnexus.domain.retrieval.fusion import rrf_fuse

        vector_hits = [
            _make_hit("chunk_a"),
            _make_hit("chunk_b"),
            _make_hit("chunk_c"),
        ]
        kw_hits = [
            _make_hit("chunk_b"),
            _make_hit("chunk_d"),
        ]

        result = rrf_fuse(vector_hits, kw_hits, k=60)

        for i in range(len(result) - 1):
            assert (
                result[i].score > result[i + 1].score
            ), f"索引 {i}: {result[i].score} 应 > {result[i+1].score}"


class TestRRFFuseCustomK:
    """k 参数可配置 — RRF 公式使用传入的 k 值。"""

    def test_custom_k_affects_scores(self) -> None:
        """较小的 k 值增大 rank 差异的影响。"""
        from ragnexus.domain.retrieval.fusion import rrf_fuse

        vector_hits = [
            _make_hit("chunk_a"),
            _make_hit("chunk_b"),
        ]

        result_k60 = rrf_fuse(vector_hits, [], k=60)
        result_k10 = rrf_fuse(vector_hits, [], k=10)

        # k=10 时 rank1 和 rank2 的分数差应更大
        diff_k60 = result_k60[0].score - result_k60[1].score
        diff_k10 = result_k10[0].score - result_k10[1].score

        assert (
            diff_k10 > diff_k60
        ), f"k=10 的分数差 ({diff_k10}) 应大于 k=60 ({diff_k60})"

    def test_explicit_k_value_is_used(self) -> None:
        """显式传入的 k 值应直接用于 RRF 公式。"""
        from ragnexus.domain.retrieval.fusion import rrf_fuse

        vector_hits = [_make_hit("chunk_a")]

        result = rrf_fuse(vector_hits, [], k=0)
        # k=0: rank1 → 1/(0+1) = 1.0
        assert result[0].score == pytest.approx(1.0)

        result = rrf_fuse(vector_hits, [], k=100)
        # k=100: rank1 → 1/(100+1) ≈ 0.0099
        assert result[0].score == pytest.approx(1 / 101)


class TestRRFFuseEdgeCases:
    """边界情况 — 空列表、大 k 值等。"""

    def test_both_empty_returns_empty_list(self) -> None:
        """两路均为空时返回空列表。"""
        from ragnexus.domain.retrieval.fusion import rrf_fuse

        result = rrf_fuse([], [], k=60)
        assert result == []

    def test_single_item_each_no_overlap(self) -> None:
        """两路各一个不重复项，正确融合。"""
        from ragnexus.domain.retrieval.fusion import rrf_fuse

        vector_hits = [_make_hit("chunk_a")]
        kw_hits = [_make_hit("chunk_b")]

        result = rrf_fuse(vector_hits, kw_hits, k=60)

        assert len(result) == 2
        scores = {h.chunk_id: h.score for h in result}
        assert scores["chunk_a"] == pytest.approx(1 / 61)
        assert scores["chunk_b"] == pytest.approx(1 / 61)

    def test_same_chunk_in_both_single_item_lists(self) -> None:
        """两路均只有同一个 chunk，应去重合并。"""
        from ragnexus.domain.retrieval.fusion import rrf_fuse

        hit = _make_hit("only_chunk")
        result = rrf_fuse([hit], [hit], k=60)

        assert len(result) == 1
        assert result[0].chunk_id == "only_chunk"
        # rank1 在两路中 → 1/(60+1) + 1/(60+1) = 2/61
        assert result[0].score == pytest.approx(2 / 61)

    def test_result_hits_are_new_objects(self) -> None:
        """返回的 SearchHit 应是新对象，不修改输入。"""
        from ragnexus.domain.retrieval.fusion import rrf_fuse

        original = _make_hit("chunk_a", score=0.95)
        result = rrf_fuse([original], [], k=60)

        # 输入未变
        assert original.score == 0.95
        # 输出是新对象，score 已重算
        assert result[0] is not original
        assert result[0].score != 0.95
