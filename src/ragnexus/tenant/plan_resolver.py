"""套餐解析器 — 纯函数，将 plan 名解析为 PlanContext。

不涉及 Redis/DB，无副作用。供路由、中间件、use case 层引用。
"""

from dataclasses import dataclass

from .plan_presets import PLAN_PRESETS


@dataclass
class PlanFeatures:
    """套餐功能开关 — 控制可选能力的启用/禁用。"""

    allowed_profiles: list[str]
    hybrid_allowed: bool
    rerank_allowed: bool
    query_rewrite_allowed: bool


@dataclass
class PlanLimits:
    """套餐用量限制 — 控制每种资源的配额上限。"""

    retrieve_qps: int
    retrieve_daily: int
    max_kb_per_retrieve: int
    max_kb: int
    max_documents_per_kb: int
    max_processing_documents: int


@dataclass
class PlanContext:
    """解析后的套餐上下文 — 将 plan 名展开为具体 features + limits。"""

    plan: str
    features: PlanFeatures
    limits: PlanLimits


def resolve_plan(plan: str) -> PlanContext:
    """纯函数：按 plan 名查找预设，返回 PlanContext。

    若 plan 名不存在则抛出 ValueError。
    """
    try:
        preset = PLAN_PRESETS[plan]
    except KeyError:
        raise ValueError(f"未知的租户套餐: {plan!r}") from None

    return PlanContext(
        plan=plan,
        features=PlanFeatures(**preset["features"]),
        limits=PlanLimits(**preset["limits"]),
    )
