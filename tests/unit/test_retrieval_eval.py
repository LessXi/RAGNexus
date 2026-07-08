"""run_retrieval_eval.py 单元测试 — resolve_kb_ids 三阶回退逻辑。

TDD RED → GREEN：先写测试，验证 resolve_kb_ids 的行为，再实现函数。
"""

from __future__ import annotations


# 待实现的函数（RED 阶段 import 将失败，符合预期）
from eval.utils import resolve_kb_ids


class TestResolveKbIds:
    """测试 per-case kb_ids 解析：case.kb_ids → case.kb_id → CLI 默认。"""

    DEFAULT = ["kb_default"]

    def test_case_has_kb_ids_list(self):
        """case 显式指定 kb_ids 列表时直接使用。"""
        case = {"question": "测试", "kb_ids": ["kb_a", "kb_b"]}
        result = resolve_kb_ids(case, self.DEFAULT)
        assert result == ["kb_a", "kb_b"]

    def test_case_has_kb_id_single_string(self):
        """case 仅指定旧字段 kb_id（单字符串）时包装为列表。"""
        case = {"question": "测试", "kb_id": "kb_legacy"}
        result = resolve_kb_ids(case, self.DEFAULT)
        assert result == ["kb_legacy"]

    def test_falls_back_to_default_when_neither_present(self):
        """case 既无 kb_ids 也无 kb_id 时回退到 CLI 默认值。"""
        case = {"question": "测试", "ground_truth": "答案"}
        result = resolve_kb_ids(case, self.DEFAULT)
        assert result == self.DEFAULT

    def test_kb_ids_wins_over_kb_id_when_both_present(self):
        """两者同时存在时 kb_ids 优先（新字段覆盖旧字段）。"""
        case = {"kb_ids": ["kb_new"], "kb_id": "kb_old"}
        result = resolve_kb_ids(case, self.DEFAULT)
        assert result == ["kb_new"]

    def test_empty_kb_ids_falls_back_to_default(self):
        """kb_ids 为空列表时被视为未指定，回退到默认值。"""
        case = {"kb_ids": [], "ground_truth": "答案"}
        result = resolve_kb_ids(case, self.DEFAULT)
        assert result == self.DEFAULT

    def test_empty_kb_ids_falls_back_to_kb_id(self):
        """kb_ids 为空列表但 kb_id 存在时使用 kb_id。"""
        case = {"kb_ids": [], "kb_id": "kb_backup"}
        result = resolve_kb_ids(case, self.DEFAULT)
        assert result == ["kb_backup"]

    def test_default_kb_ids_empty(self):
        """CLI 默认值为空列表时也能返回空列表。"""
        case = {"question": "测试"}
        result = resolve_kb_ids(case, [])
        assert result == []
