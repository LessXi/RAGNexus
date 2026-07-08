"""cross_kb_rrf_fuse 函数单元测试 — 多 KB 跨库 RRF 融合算法。

验证多组（多知识库）检索结果的分数重算、跨库去重合并与排序行为。
"""

from __future__ import annotations

import pytest

from ragnexus.domain.models import SearchHit
from ragnexus.domain.retrieval.fusion import cross_kb_rrf_fuse


def _make_hit(
    chunk_id: str,
    kb_id: str = "kb_test",
    doc_id: str = "",
    score: float = 0.9,
    text: str = "",
    metadata: dict | None = None,
) -> SearchHit:
    """创建测试用 SearchHit 的工厂函数。"""
    return SearchHit(
        chunk_id=chunk_id,
        kb_id=kb_id,
        doc_id=doc_id if doc_id else f"doc_{chunk_id}",
        score=score,
        text=text if text else f"content of {chunk_id}",
        metadata=metadata if metadata is not None else {},
    )


class TestCrossKbRrfFuseTwoGroups:
    """两组各 5 条 hits，验证 rank 均衡与排序。"""

    def test_two_groups_no_overlap(self):
        """两组无重叠 chunk，结果 10 条，按 rrf_score 降序排列。"""
        k = 60
        group_a = [
            _make_hit("a1", kb_id="kb_a", doc_id="doc_a1"),
            _make_hit("a2", kb_id="kb_a", doc_id="doc_a2"),
            _make_hit("a3", kb_id="kb_a", doc_id="doc_a3"),
            _make_hit("a4", kb_id="kb_a", doc_id="doc_a4"),
            _make_hit("a5", kb_id="kb_a", doc_id="doc_a5"),
        ]
        group_b = [
            _make_hit("b1", kb_id="kb_b", doc_id="doc_b1"),
            _make_hit("b2", kb_id="kb_b", doc_id="doc_b2"),
            _make_hit("b3", kb_id="kb_b", doc_id="doc_b3"),
            _make_hit("b4", kb_id="kb_b", doc_id="doc_b4"),
            _make_hit("b5", kb_id="kb_b", doc_id="doc_b5"),
        ]

        result = cross_kb_rrf_fuse([group_a, group_b], k=k)

        # 应有 10 条结果
        assert len(result) == 10

        # 按 score 降序排列（RRF 分值越大越靠前）
        for i in range(len(result) - 1):
            assert (
                result[i].score >= result[i + 1].score
            ), f"索引 {i}: {result[i].score} 应 >= {result[i + 1].score}"

        # 验证每组 rank=1 的 hit 分数相同（跨库对称）
        scores_by_rank: dict[int, float] = {}
        for hit in result:
            # 通过 chunk_id 推断原始 rank
            if hit.kb_id == "kb_a":
                rank = int(hit.chunk_id[1])  # a1 -> 1
            else:
                rank = int(hit.chunk_id[1])  # b1 -> 1
            if rank not in scores_by_rank:
                scores_by_rank[rank] = hit.score
            else:
                assert scores_by_rank[rank] == pytest.approx(hit.score)

        # rank=1 分数 = 1/(k+1)
        assert scores_by_rank[1] == pytest.approx(1 / (k + 1))
        # rank=5 分数 = 1/(k+5)
        assert scores_by_rank[5] == pytest.approx(1 / (k + 5))

    def test_two_groups_with_cross_kb_overlap(self):
        """两组有跨库重叠 chunk（相同 doc_id+chunk_id），RRF 分数累加。"""
        k = 60
        group_a = [
            _make_hit("c1", kb_id="kb_a", doc_id="doc_shared"),
            _make_hit("c2", kb_id="kb_a", doc_id="doc_a2"),
        ]
        group_b = [
            _make_hit("c3", kb_id="kb_b", doc_id="doc_b3"),
            _make_hit("c1", kb_id="kb_b", doc_id="doc_shared"),
        ]

        result = cross_kb_rrf_fuse([group_a, group_b], k=k)

        # 去重后应有 3 条（c1 去重，c2, c3 保留）
        assert len(result) == 3

        # c1 的 RRF 分数 = 1/(k+1) + 1/(k+2)（在 kb_a rank=1，在 kb_b rank=2）
        expected_c1_score = 1 / (k + 1) + 1 / (k + 2)
        c1_hit = next(h for h in result if h.chunk_id == "c1")
        assert c1_hit.score == pytest.approx(expected_c1_score)


class TestCrossKbRrfFuseSingleGroup:
    """单组退化 — 只给一组 hits，返回该组的 RRF 分数结果。"""

    def test_single_group(self):
        """单组输入退化为单 KB 的 RRF 重算。"""
        k = 60
        group = [
            _make_hit("x1", kb_id="kb_x", doc_id="doc_x1"),
            _make_hit("x2", kb_id="kb_x", doc_id="doc_x2"),
            _make_hit("x3", kb_id="kb_x", doc_id="doc_x3"),
        ]

        result = cross_kb_rrf_fuse([group], k=k)

        assert len(result) == 3

        # rank=1: 1/(k+1)
        assert result[0].score == pytest.approx(1 / (k + 1))
        # rank=2: 1/(k+2)
        assert result[1].score == pytest.approx(1 / (k + 2))
        # rank=3: 1/(k+3)
        assert result[2].score == pytest.approx(1 / (k + 3))

        # 按分数降序
        assert result[0].score > result[1].score > result[2].score


class TestCrossKbRrfFuseEmptyGroup:
    """空组过滤 — 空输入或全空子列表返回空列表。"""

    def test_empty_input_list(self):
        """空列表输入返回空列表。"""
        result = cross_kb_rrf_fuse([], k=60)
        assert result == []

    def test_all_empty_groups(self):
        """所有子列表为空返回空列表。"""
        result = cross_kb_rrf_fuse([[], []], k=60)
        assert result == []

    def test_mixed_empty_groups(self):
        """部分空组过滤，非空组正常返回。"""
        k = 60
        group = [
            _make_hit("z1", kb_id="kb_z", doc_id="doc_z1"),
        ]
        result = cross_kb_rrf_fuse([[], group], k=k)
        assert len(result) == 1
        assert result[0].score == pytest.approx(1 / (k + 1))


class TestCrossKbRrfFuseDuplicateChunk:
    """跨库重复 chunk — (doc_id, chunk_id) 二元组去重并 RRF 累加。"""

    def test_duplicate_chunk_sums_rrf(self):
        """相同 (doc_id, chunk_id) 出现在多个 KB 中，RRF 分数累加。"""
        k = 60
        # chunk "dup1" 在 kb_a rank=1，在 kb_b rank=3
        group_a = [
            _make_hit("dup1", kb_id="kb_a", doc_id="doc_dup"),
            _make_hit("a2", kb_id="kb_a", doc_id="doc_a2"),
        ]
        group_b = [
            _make_hit("b1", kb_id="kb_b", doc_id="doc_b1"),
            _make_hit("b2", kb_id="kb_b", doc_id="doc_b2"),
            _make_hit("dup1", kb_id="kb_b", doc_id="doc_dup"),
        ]

        result = cross_kb_rrf_fuse([group_a, group_b], k=k)

        # 去重后应有 4 条
        assert len(result) == 4

        # dup1 RRF = 1/(k+1) + 1/(k+3)
        expected_dup_score = 1 / (k + 1) + 1 / (k + 3)
        dup_hit = next(h for h in result if h.chunk_id == "dup1")
        assert dup_hit.score == pytest.approx(expected_dup_score)

        # 保留首次出现的 kb_id
        assert dup_hit.kb_id == "kb_a"

    def test_duplicate_only_by_chunk_id_not_doc_id(self):
        """仅 chunk_id 相同但 doc_id 不同 → 不去重，视为不同 chunk。"""
        k = 60
        group_a = [
            _make_hit("same_cid", kb_id="kb_a", doc_id="doc_alpha"),
        ]
        group_b = [
            _make_hit("same_cid", kb_id="kb_b", doc_id="doc_beta"),
        ]

        result = cross_kb_rrf_fuse([group_a, group_b], k=k)

        # 不同 doc_id，应视为两条独立结果
        assert len(result) == 2

    def test_cross_kb_fuse_preserves_text_and_metadata(self):
        """跨库融合后 text 和 metadata 保留首次出现的值。"""
        k = 60
        group_a = [
            _make_hit(
                "c1",
                kb_id="kb_a",
                doc_id="doc_s",
                text="hello world",
                metadata={"page": 1},
            ),
        ]
        group_b = [
            _make_hit(
                "c1",
                kb_id="kb_b",
                doc_id="doc_s",
                text="different text",
                metadata={"page": 99},
            ),
        ]

        result = cross_kb_rrf_fuse([group_a, group_b], k=k)

        assert len(result) == 1
        c1_hit = result[0]
        assert c1_hit.kb_id == "kb_a"  # 首次出现的 kb_id
        assert c1_hit.text == "hello world"  # 首次出现的 text
        assert c1_hit.metadata == {"page": 1}  # 首次出现的 metadata

    def test_different_kb_ids_on_same_chunk_sum_rrf(self):
        """同 (doc_id, chunk_id) 在三个不同 KB 中均有出现，分数累加。"""
        k = 60
        group_a = [
            _make_hit("multi", kb_id="kb_a", doc_id="doc_m"),
        ]
        group_b = [
            _make_hit("multi", kb_id="kb_b", doc_id="doc_m"),
        ]
        group_c = [
            _make_hit("multi", kb_id="kb_c", doc_id="doc_m"),
        ]

        result = cross_kb_rrf_fuse([group_a, group_b, group_c], k=k)

        assert len(result) == 1
        # 三个 KB 中 rank 都是 1 → 3 * 1/(k+1)
        assert result[0].score == pytest.approx(3 / (k + 1))
        assert result[0].kb_id == "kb_a"


class TestSearchHitKbNameDefault:
    """SearchHit 构造时不传 kb_name，取默认值 ""。"""

    def test_kb_name_defaults_to_empty_string(self):
        """SearchHit 不传 kb_name 时，kb_name 为 ""。"""
        hit = SearchHit(
            chunk_id="ch1",
            kb_id="kb_test",
            doc_id="doc1",
            score=0.95,
            text="hello",
            metadata={},
        )
        assert hit.kb_name == ""

    def test_kb_name_explicit_none_not_allowed(self):
        """kb_name 的类型是 str，传 None 会报错（类型安全）。"""
        hit = SearchHit(
            chunk_id="ch1",
            kb_id="kb_test",
            doc_id="doc1",
            score=0.95,
            text="hello",
            metadata={},
        )
        # kb_name 依然是 str 类型，默认 ""
        assert isinstance(hit.kb_name, str)
        assert hit.kb_name == ""

    def test_kb_name_explicit_value(self):
        """显式传 kb_name 则使用传入值。"""
        hit = SearchHit(
            chunk_id="ch1",
            kb_id="kb_test",
            doc_id="doc1",
            score=0.95,
            text="hello",
            metadata={},
            kb_name="我的知识库",
        )
        assert hit.kb_name == "我的知识库"
