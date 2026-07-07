"""工厂函数: create_kb_router — GET/PATCH/DELETE /v1/knowledge-bases/{kb_id}。"""

from fastapi import APIRouter, Body, Depends

from ragnexus.core.auth import TenantContext


def create_kb_router(uc_detail, uc_update, uc_delete, get_current_tenant) -> APIRouter:
    """返回含 GET/PATCH/DELETE 三个端点的 APIRouter。

    ``uc_detail``   — ``async def execute(kb_id, tenant_id) -> KnowledgeBase``
    ``uc_update``   — ``async def execute(kb_id, tenant_id, *, name, description, settings) -> KnowledgeBase``
    ``uc_delete``   — ``async def execute(kb_id, tenant_id) -> None``
    """

    router = APIRouter()

    @router.get("/v1/knowledge-bases/{kb_id}")
    async def get_kb(
        kb_id: str,
        current_tenant: TenantContext = Depends(get_current_tenant),
    ):
        kb = await uc_detail.execute(kb_id, current_tenant.tenant_id)
        return {
            "code": 0,
            "data": {
                "id": kb.id,
                "name": kb.name,
                "description": kb.description,
                "settings": kb.settings,
                "tenant_id": kb.tenant_id,
                "created_at": kb.created_at.isoformat(),
            },
            "message": "ok",
        }

    @router.patch("/v1/knowledge-bases/{kb_id}")
    async def update_kb(
        kb_id: str,
        name: str | None = Body(None),
        description: str | None = Body(None),
        settings: dict | None = Body(None),
        current_tenant: TenantContext = Depends(get_current_tenant),
    ):
        kb = await uc_update.execute(
            kb_id,
            current_tenant.tenant_id,
            name=name,
            description=description,
            settings=settings,
        )
        return {
            "code": 0,
            "data": {
                "id": kb.id,
                "name": kb.name,
                "description": kb.description,
                "settings": kb.settings,
                "tenant_id": kb.tenant_id,
                "created_at": kb.created_at.isoformat(),
            },
            "message": "ok",
        }

    @router.delete("/v1/knowledge-bases/{kb_id}")
    async def delete_kb(
        kb_id: str,
        current_tenant: TenantContext = Depends(get_current_tenant),
    ):
        await uc_delete.execute(kb_id, current_tenant.tenant_id)
        return {"code": 0, "data": None, "message": "ok"}

    return router
