"""Parser Schema 兼容性单元测试。

验证 rerank/rewrite parser 能兼容 LLM 多种输出格式。
LLM（尤其 deepseek-v4-flash-free）同一 query 不同次可能返回不同 JSON schema，
parser 必须容错所有常见格式，否则会触发降级。

覆盖场景（基于真实 demo 日志观察到的 schema）：
- rerank: rankings / rerank_scores / scores / results key + 扁平 dict + 纯 list
- rewrite: 缺 needs_rewrite 字段时从 query/rewritten_query 推断
"""

from __future__ import annotations

from ragnexus.adapters.rerank.llm import (
    _extract_rankings_from_dict,
    _parse_rankings_json,
)
from ragnexus.adapters.rewrite.llm import _parse_rewrite_json


# ═══════════════════════════════════════════════════════════════════
# Rerank Parser — _extract_rankings_from_dict
# ═══════════════════════════════════════════════════════════════════


class TestExtractRankingsFromDict:
    """_extract_rankings_from_dict 应兼容多种 LLM 输出 schema。"""

    def test_standard_rankings_key(self) -> None:
        """标准格式: {"rankings": [{"chunk_id": ..., "rerank_score": ...}]}。"""
        d = {"rankings": [{"chunk_id": "a", "rerank_score": 0.9}]}
        result = _extract_rankings_from_dict(d)
        assert result == [{"chunk_id": "a", "rerank_score": 0.9}]

    def test_rerank_scores_key(self) -> None:
        """嵌套格式: {"rerank_scores": [...]}（deepseek-v4-flash-free 实际输出）。"""
        d = {
            "rerank_scores": [
                {"chunk_id": "doc:6", "rerank_score": 0.95},
                {"chunk_id": "doc:4", "rerank_score": 0.9},
            ]
        }
        result = _extract_rankings_from_dict(d)
        assert result is not None
        assert len(result) == 2
        assert result[0]["chunk_id"] == "doc:6"

    def test_scores_key(self) -> None:
        """备选 key: {"scores": [...]}。"""
        d = {"scores": [{"chunk_id": "x", "rerank_score": 0.5}]}
        result = _extract_rankings_from_dict(d)
        assert result == [{"chunk_id": "x", "rerank_score": 0.5}]

    def test_results_key(self) -> None:
        """备选 key: {"results": [...]}。"""
        d = {"results": [{"chunk_id": "y", "rerank_score": 0.7}]}
        result = _extract_rankings_from_dict(d)
        assert result == [{"chunk_id": "y", "rerank_score": 0.7}]

    def test_flat_dict(self) -> None:
        """扁平格式: {chunk_id: score}（deepseek-v4-flash-free 实际输出）。"""
        d = {"doc:0": 0.1, "doc:5": 0.95, "doc:3": 0.9}
        result = _extract_rankings_from_dict(d)
        assert result is not None
        assert len(result) == 3
        # 转换后每个元素应有 chunk_id 和 rerank_score
        ids = {item["chunk_id"] for item in result}
        assert ids == {"doc:0", "doc:5", "doc:3"}
        scores = {item["rerank_score"] for item in result}
        assert scores == {0.1, 0.95, 0.9}

    def test_empty_dict(self) -> None:
        """空 dict 返回 None。"""
        assert _extract_rankings_from_dict({}) is None

    def test_non_dict(self) -> None:
        """非 dict 输入返回 None。"""
        assert _extract_rankings_from_dict("not a dict") is None  # type: ignore[arg-type]
        assert _extract_rankings_from_dict(None) is None  # type: ignore[arg-type]

    def test_dict_with_mixed_values(self) -> None:
        """dict 的 value 不全是数字时不当作扁平 dict。"""
        d = {"rankings": "not a list", "extra": 0.5}
        # rankings 不是 list，且不是全数字扁平 dict → None
        assert _extract_rankings_from_dict(d) is None


# ═══════════════════════════════════════════════════════════════════
# Rerank Parser — _parse_rankings_json（端到端，含字符串解析）
# ═══════════════════════════════════════════════════════════════════


class TestParseRankingsJson:
    """_parse_rankings_json 端到端测试 — 含 dict 输入和字符串解析。"""

    def test_dict_input_rerank_scores(self) -> None:
        """dict 输入 + rerank_scores key → 正确提取。"""
        raw = {"rerank_scores": [{"chunk_id": "a", "rerank_score": 0.8}]}
        result = _parse_rankings_json(raw)
        assert result == [{"chunk_id": "a", "rerank_score": 0.8}]

    def test_dict_input_flat(self) -> None:
        """dict 输入 + 扁平格式 → 转换为 list。"""
        raw = {"doc:1": 0.2, "doc:2": 0.9}
        result = _parse_rankings_json(raw)
        assert len(result) == 2

    def test_list_input(self) -> None:
        """纯 list 输入 → 直接返回。"""
        raw = [{"chunk_id": "a", "rerank_score": 0.5}]
        result = _parse_rankings_json(raw)
        assert result == raw

    def test_empty_dict(self) -> None:
        """空 dict → 空列表（降级）。"""
        assert _parse_rankings_json({}) == []

    def test_empty_list(self) -> None:
        """空 list → 空列表。"""
        assert _parse_rankings_json([]) == []

    def test_json_string_rerank_scores(self) -> None:
        """JSON 字符串含 rerank_scores key → Layer 2 解析。"""
        import json

        raw = json.dumps({"rerank_scores": [{"chunk_id": "x", "rerank_score": 0.6}]})
        result = _parse_rankings_json(raw)
        assert result == [{"chunk_id": "x", "rerank_score": 0.6}]


# ═══════════════════════════════════════════════════════════════════
# Rewrite Parser — _parse_rewrite_json
# ═══════════════════════════════════════════════════════════════════


class TestParseRewriteJson:
    """_parse_rewrite_json 应兼容 LLM 缺失 needs_rewrite 字段的输出。"""

    def test_complete_schema(self) -> None:
        """完整字段: needs_rewrite + rewritten_query + reason。"""
        raw = {
            "needs_rewrite": True,
            "rewritten_query": "优化检索准确率的方法",
            "reason": "口语化表达",
        }
        result = _parse_rewrite_json(raw, original_query="怎么优化检索的准确率")
        assert result["needs_rewrite"] is True
        assert result["rewritten_query"] == "优化检索准确率的方法"

    def test_missing_needs_rewrite_with_query(self) -> None:
        """LLM 只返回 {"query": "..."} → Layer 4.5 推断 needs_rewrite。"""
        raw = {"query": "如何优化检索准确率"}
        result = _parse_rewrite_json(raw, original_query="怎么优化检索的准确率")
        # query 和 original_query 不同 → needs_rewrite=True
        assert result["needs_rewrite"] is True
        assert result["rewritten_query"] == "如何优化检索准确率"
        assert "推断" in result["reason"]

    def test_missing_needs_rewrite_same_query(self) -> None:
        """LLM 返回的 query 等于原始 query → needs_rewrite=False。"""
        raw = {"query": "怎么优化检索的准确率"}
        result = _parse_rewrite_json(raw, original_query="怎么优化检索的准确率")
        assert result["needs_rewrite"] is False

    def test_missing_needs_rewrite_with_rewritten_query(self) -> None:
        """LLM 只返回 {"rewritten_query": "..."} → Layer 4.5 推断。"""
        raw = {"rewritten_query": "优化检索准确率的方法"}
        result = _parse_rewrite_json(raw, original_query="怎么优化检索的准确率")
        assert result["needs_rewrite"] is True
        assert result["rewritten_query"] == "优化检索准确率的方法"

    def test_missing_needs_rewrite_no_query(self) -> None:
        """LLM 既没 needs_rewrite 也没 query/rewritten_query → 降级。"""
        raw = {"reason": "无法处理"}
        result = _parse_rewrite_json(raw, original_query="test")
        assert result.get("_degraded") is True

    def test_needs_rewrite_not_bool(self) -> None:
        """needs_rewrite 不是布尔值 → 降级。"""
        raw = {"needs_rewrite": "yes", "rewritten_query": "x"}
        result = _parse_rewrite_json(raw, original_query="test")
        assert result.get("_degraded") is True

    def test_needs_rewrite_true_empty_query(self) -> None:
        """needs_rewrite=True 但 rewritten_query 为空 → 降级。"""
        raw = {"needs_rewrite": True, "rewritten_query": ""}
        result = _parse_rewrite_json(raw, original_query="test")
        assert result.get("_degraded") is True

    def test_needs_rewrite_false(self) -> None:
        """needs_rewrite=False → 正常返回，不改写。"""
        raw = {"needs_rewrite": False, "reason": "已足够清晰"}
        result = _parse_rewrite_json(raw, original_query="test")
        assert result["needs_rewrite"] is False

    def test_json_string_input(self) -> None:
        """JSON 字符串输入 → 解析成功。"""
        import json

        raw = json.dumps(
            {"needs_rewrite": True, "rewritten_query": "改写后", "reason": "x"}
        )
        result = _parse_rewrite_json(raw, original_query="原始")
        assert result["needs_rewrite"] is True
        assert result["rewritten_query"] == "改写后"

    def test_preserves_llm_reason(self) -> None:
        """Layer 4.5 不覆盖 LLM 自带的 reason 字段。"""
        raw = {"query": "改写后", "reason": "LLM 自己的解释"}
        result = _parse_rewrite_json(raw, original_query="原始")
        assert result["reason"] == "LLM 自己的解释"
