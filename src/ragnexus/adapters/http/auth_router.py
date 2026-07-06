"""鉴权路由——GET /v1/auth/me 返回当前 API Key 的租户信息（含 plan、features、limits、usage）。"""

from fastapi import APIRouter, Depends

from ragnexus.core.auth import TenantContext
from ragnexus.tenant.plan_resolver import resolve_plan


def create_auth_router(
    get_current_tenant, tenant_repo=None, rate_limiter=None
) -> APIRouter:
    """创建鉴权路由。

    参数：
        get_current_tenant: make_get_current_tenant 返回的 Depends 可调用对象
        tenant_repo:      PgTenantRepository（可选），用于查询 kb_count
        rate_limiter:     RateLimitService（可选），用于查询每日检索量
    """
    router = APIRouter(prefix="/v1/auth", tags=["auth"])

    @router.get("/me")
    async def auth_me(
        current_tenant: TenantContext = Depends(get_current_tenant),  # noqa: B008
    ):
        """返回当前 Key 的租户信息（含套餐与用量）。

        在请求头中携带 `Authorization: Bearer rk_live_<hex>`，
        本端点返回该 Key 所属租户的基本信息、套餐配置和当前用量。
        """
        plan_ctx = resolve_plan(current_tenant.plan)

        # usage.kb_count
        kb_count = 0
        if tenant_repo:
            kb_count = (
                await tenant_repo.pool.fetchval(
                    "SELECT count(*) FROM knowledge_bases WHERE tenant_id=$1",
                    current_tenant.tenant_id,
                )
                or 0
            )

        # usage.retrieve_daily_count
        daily_count = 0
        if rate_limiter:
            daily_count = await rate_limiter.get_daily_count(current_tenant.tenant_id)

        return {
            "tenant_id": current_tenant.tenant_id,
            "tenant_name": current_tenant.tenant_name,
            "key_id": current_tenant.key_id,
            "key_prefix": current_tenant.key_prefix,
            "plan": current_tenant.plan,
            "features": plan_ctx.features.__dict__,
            "limits": plan_ctx.limits.__dict__,
            "usage": {
                "kb_count": kb_count,
                "retrieve_daily_count": daily_count,
            },
        }

    return router
