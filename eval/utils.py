"""eval 工具函数 — 纯逻辑，零外部依赖，可被测试直接导入。"""

from __future__ import annotations


def resolve_kb_ids(case: dict, default_kb_ids: list[str]) -> list[str]:
    """从 case 解析 kb_ids，三阶回退：case.kb_ids → case.kb_id → 默认值。

    Args:
        case: 单条 golden case 字典，可能包含 kb_ids 或 kb_id 字段。
        default_kb_ids: CLI 传入的默认知识库 ID 列表。

    Returns:
        解析后的知识库 ID 列表。

    回退规则：
        1. case.kb_ids 非空列表 → 直接使用
        2. case.kb_id 非空字符串 → 包装为 [kb_id]
        3. 以上均无 → 回退到 default_kb_ids
    """
    kb_ids = case.get("kb_ids")
    if kb_ids and isinstance(kb_ids, list):
        return [str(k) for k in kb_ids]

    kb_id = case.get("kb_id")
    if kb_id and isinstance(kb_id, str):
        return [kb_id]

    return default_kb_ids
