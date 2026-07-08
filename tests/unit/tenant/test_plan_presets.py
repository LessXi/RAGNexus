"""plan_presets 数据字段单元测试。
验证 PLAN_PRESETS 三档套餐的 limits.max_kb_per_retrieve 值。
"""

from ragnexus.tenant.plan_presets import PLAN_PRESETS


def test_max_kb_per_retrieve_free():
    """free 套餐 max_kb_per_retrieve 为 1。"""
    assert PLAN_PRESETS["free"]["limits"]["max_kb_per_retrieve"] == 1


def test_max_kb_per_retrieve_standard():
    """standard 套餐 max_kb_per_retrieve 为 3。"""
    assert PLAN_PRESETS["standard"]["limits"]["max_kb_per_retrieve"] == 3


def test_max_kb_per_retrieve_pro():
    """pro 套餐 max_kb_per_retrieve 为 5。"""
    assert PLAN_PRESETS["pro"]["limits"]["max_kb_per_retrieve"] == 5


def test_all_plans_have_max_kb_per_retrieve():
    """所有三个套餐都包含 max_kb_per_retrieve 字段。"""
    for plan in ["free", "standard", "pro"]:
        assert (
            "max_kb_per_retrieve" in PLAN_PRESETS[plan]["limits"]
        ), f"{plan} 套餐缺少 max_kb_per_retrieve"
