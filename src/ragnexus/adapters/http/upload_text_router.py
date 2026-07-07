"""工厂函数: upload_text_router — POST /v1/documents:upload-text (JSON)。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ragnexus.core.auth import TenantContext


class UploadTextRequest(BaseModel):
    kb_id: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=256)
    content: str = Field(..., min_length=1)


def create_router(uc, get_current_tenant, quota_svc=None) -> APIRouter:
    """返回含单个 JSON POST 端点的 APIRouter。

    ``uc`` 必须提供 ``async def execute(
        *, kb_id: str, file_content: bytes, filename: str, content_type: str,
        tenant_id: str, text_content: str | None = None,
    ) -> UploadResult``。
    """

    router = APIRouter()

    @router.post("/v1/documents:upload-text", status_code=201)
    async def upload_text(
        body: UploadTextRequest,
        current_tenant: TenantContext = Depends(get_current_tenant),
    ):
        if quota_svc:
            await quota_svc.check_doc_upload(
                body.kb_id, current_tenant.tenant_id, current_tenant.plan
            )

        file_content = body.content.encode("utf-8")
        content_type = "text/markdown" if body.title.endswith(".md") else "text/plain"
        filename = body.title if "." in body.title else body.title + ".md"

        result = await uc.execute(
            kb_id=body.kb_id,
            file_content=file_content,
            filename=filename,
            content_type=content_type,
            tenant_id=current_tenant.tenant_id,
            text_content=body.content,
        )
        return {
            "code": 0,
            "data": {
                "doc_id": result.doc_id,
                "kb_id": result.kb_id,
                "status": result.status.name.lower(),
                "chunk_count": result.chunk_count,
            },
            "message": "ok",
        }

    return router
