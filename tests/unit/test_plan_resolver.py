"""plan_resolver 纯函数单元测试 — TDD RED → GREEN。

测试计划解析、预设结构验证、Tenant.plan 默认值。
"""

import pytest


# ── RED: 模块尚不存在时的导入测试 ──


def test_resolve_plan_free_basic():
    """resolve_plan("free") 返回 PlanContext，包含正确的 plan 名和 features/limits。"""
    from ragnexus.tenant.plan_resolver import resolve_plan  # noqa: E402

    ctx = resolve_plan("free")
    assert ctx.plan == "free"
    assert ctx.features.rerank_allowed is False
    assert ctx.features.hybrid_allowed is False
    assert ctx.features.query_rewrite_allowed is False
    assert ctx.features.allowed_profiles == ["speed"]
    assert ctx.limits.retrieve_qps == 3
    assert ctx.limits.max_kb == 1

    ctx2 = resolve_plan("pro")
    assert ctx2.plan == "pro"
    assert ctx2.features.rerank_allowed is True
    assert ctx2.features.hybrid_allowed is True
    assert ctx2.features.query_rewrite_allowed is True
    assert ctx2.features.allowed_profiles == ["speed", "balanced", "quality", "custom"]
    assert ctx2.limits.max_kb == 50
    assert ctx2.limits.max_documents_per_kb == 5000


def test_resolve_plan_unknown_raises_valueerror():
    """resolve_plan("unknown") 抛出 ValueError。"""
    from ragnexus.tenant.plan_resolver import resolve_plan  # noqa: E402

    with pytest.raises(ValueError, match="unknown"):
        resolve_plan("unknown")


def test_plan_presets_structure():
    """PLAN_PRESETS 包含 free、standard、pro 三档，结构完整。"""
    from ragnexus.tenant.plan_presets import PLAN_PRESETS  # noqa: E402

    assert set(PLAN_PRESETS.keys()) == {"free", "standard", "pro"}

    for plan_name, preset in PLAN_PRESETS.items():
        assert "features" in preset, f"{plan_name} 缺少 features"
        assert "limits" in preset, f"{plan_name} 缺少 limits"

        feats = preset["features"]
        assert "allowed_profiles" in feats
        assert "hybrid_allowed" in feats
        assert "rerank_allowed" in feats
        assert "query_rewrite_allowed" in feats

        limits = preset["limits"]
        assert "retrieve_qps" in limits
        assert "retrieve_daily" in limits
        assert "max_kb" in limits
        assert "max_documents_per_kb" in limits
        assert "max_processing_documents" in limits


def test_retrieve_profile_presets_structure():
    """RETRIEVE_PROFILE_PRESETS 包含 speed、balanced、quality，不含 custom。"""
    from ragnexus.tenant.retrieve_presets import RETRIEVE_PROFILE_PRESETS  # noqa: E402

    assert set(RETRIEVE_PROFILE_PRESETS.keys()) == {"speed", "balanced", "quality"}
    assert "custom" not in RETRIEVE_PROFILE_PRESETS

    # speed 档验证
    speed = RETRIEVE_PROFILE_PRESETS["speed"]
    assert speed["mode"] == "vector"
    assert speed["top_k"] == 3
    assert speed["rerank_enabled"] is False
    assert speed["query_options"]["enabled"] is False

    # balanced 档验证
    balanced = RETRIEVE_PROFILE_PRESETS["balanced"]
    assert balanced["mode"] == "hybrid"
    assert balanced["top_k"] == 5

    # quality 档验证
    quality = RETRIEVE_PROFILE_PRESETS["quality"]
    assert quality["mode"] == "hybrid"
    assert quality["top_k"] == 8
    assert quality["rerank_enabled"] is True
    assert quality["rerank_top_n"] == 5
    assert quality["query_options"]["enabled"] is True
    assert quality["query_options"]["strategy"] == "rewrite"


def test_tenant_plan_default():
    """Tenant dataclass 的 plan 字段默认值为 "free"。"""
    from ragnexus.domain.models import Tenant  # noqa: E402

    t = Tenant(id="t1", name="test")
    assert t.plan == "free"

    t2 = Tenant(id="t2", name="pro user", plan="pro")
    assert t2.plan == "pro"
