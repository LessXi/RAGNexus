"""文档运维路由工厂。"""

from fastapi import APIRouter, Depends
from ragnexus.core.auth import TenantContext


def create_document_router(
    uc_query, uc_delete, uc_reindex, get_current_tenant, quota_svc=None
) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/documents/{doc_id}")
    async def get_document(
        doc_id: str, current_tenant: TenantContext = Depends(get_current_tenant)
    ):
        doc = await uc_query.execute(doc_id, current_tenant.tenant_id)
        return {
            "code": 0,
            "data": {
                "doc_id": doc.doc_id,
                "kb_id": doc.kb_id,
                "filename": doc.filename,
                "file_hash": doc.file_hash,
                "file_size": doc.file_size,
                "content_type": doc.content_type,
                "status": doc.status.name.lower(),
                "chunk_count": doc.chunk_count,
                "error_message": doc.error_message,
                "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
                "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
            },
            "message": "ok",
        }

    @router.delete("/v1/documents/{doc_id}")
    async def delete_document(
        doc_id: str, current_tenant: TenantContext = Depends(get_current_tenant)
    ):
        await uc_delete.execute(doc_id, current_tenant.tenant_id)
        return {"code": 0, "data": None, "message": "ok"}

    @router.post("/v1/documents/{doc_id}/reindex")
    async def reindex_document(
        doc_id: str, current_tenant: TenantContext = Depends(get_current_tenant)
    ):
        if quota_svc:
            await quota_svc.check_processing(
                current_tenant.tenant_id, current_tenant.plan
            )

        result = await uc_reindex.execute(doc_id, current_tenant.tenant_id)
        return {"code": 0, "data": result, "message": "ok"}

    return router
