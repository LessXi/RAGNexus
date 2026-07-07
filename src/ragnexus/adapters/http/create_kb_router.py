"""工厂函数: create_kb_router — POST /v1/knowledge-bases:create。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ragnexus.core.auth import TenantContext


class _CreateKBRequest(BaseModel):
    model_config = {"extra": "ignore"}
    name: str = Field(..., min_length=1, max_length=64)
    description: str = Field(default="", max_length=256)


def create_router(uc, get_current_tenant, quota_svc=None) -> APIRouter:
    """返回含单个 POST 端点的 APIRouter。

    ``uc`` 必须提供 ``async def execute(*, name: str, tenant_id: str) -> KnowledgeBase``。
    """

    router = APIRouter()

    @router.post("/v1/knowledge-bases:create")
    async def create_kb(
        req: _CreateKBRequest,
        current_tenant: TenantContext = Depends(get_current_tenant),
    ):
        if quota_svc:
            await quota_svc.check_kb_count(
                current_tenant.tenant_id, current_tenant.plan
            )

        result = await uc.execute(name=req.name, tenant_id=current_tenant.tenant_id)
        return {
            "code": 0,
            "data": {
                "kb_id": result.id,
                "name": result.name,
                "tenant_id": result.tenant_id,
                "created_at": result.created_at.isoformat(),
            },
            "message": "ok",
        }

    return router
