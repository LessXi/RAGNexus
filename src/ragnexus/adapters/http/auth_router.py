"""鉴权路由——GET /v1/auth/me 返回当前 API Key 的租户信息。"""

from fastapi import APIRouter, Depends

from ragnexus.core.auth import TenantContext


def create_auth_router(get_current_tenant) -> APIRouter:
    """创建鉴权路由。

    参数：
        get_current_tenant: make_get_current_tenant 返回的 Depends 可调用对象
    """
    router = APIRouter(prefix="/v1/auth", tags=["auth"])

    @router.get("/me")
    async def auth_me(
        current_tenant: TenantContext = Depends(get_current_tenant),  # noqa: B008
    ):
        """返回当前 Key 的租户信息。

        在请求头中携带 `Authorization: Bearer rk_live_<hex>`，
        本端点返回该 Key 所属租户的基本信息，用于前端展示当前用户身份。
        """
        return {
            "tenant_id": current_tenant.tenant_id,
            "tenant_name": current_tenant.tenant_name,
            "key_id": current_tenant.key_id,
            "key_prefix": current_tenant.key_prefix,
        }

    return router
