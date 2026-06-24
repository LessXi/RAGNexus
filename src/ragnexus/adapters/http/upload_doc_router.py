"""Factory: upload_doc_router — POST /v1/documents:upload (multipart)."""

from fastapi import APIRouter, File, Form, UploadFile


def create_router(uc) -> APIRouter:
    """Return an APIRouter with a single multipart POST endpoint.

    ``uc`` must have ``async def execute(
        *, kb_id: str, file_content: bytes, filename: str, content_type: str,
    ) -> UploadResult``.
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
                "chunk_count": len(result.chunks),
            },
            "message": "ok",
        }

    return router
