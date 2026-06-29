"""工厂函数: upload_doc_router — POST /v1/documents:upload（multipart）。"""

from fastapi import APIRouter, File, Form, UploadFile


def create_router(uc) -> APIRouter:
    """返回含单个 multipart POST 端点的 APIRouter。

    ``uc`` 必须提供 ``async def execute(
        *, kb_id: str, file_content: bytes, filename: str, content_type: str,
    ) -> UploadResult``。
    """

    router = APIRouter()

    @router.post("/v1/documents:upload", status_code=201)
    async def upload_doc(
        kb_id: str = Form(...),
        file: UploadFile = File(...),  # noqa: B008
    ):
        content = await file.read()
        result = await uc.execute(
            kb_id=kb_id,
            file_content=content,
            filename=file.filename or "unknown",
            content_type=file.content_type or "application/octet-stream",
        )
        return {
            "code": 0,
            "data": {
                "doc_id": result.doc_id,
                "kb_id": result.kb_id,
                "chunk_count": result.chunk_count,
            },
            "message": "ok",
        }

    return router
