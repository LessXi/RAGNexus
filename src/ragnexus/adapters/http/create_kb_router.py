"""Factory: create_kb_router — POST /v1/knowledge-bases:create."""

from fastapi import APIRouter
from pydantic import BaseModel, Field


class _CreateKBRequest(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(..., min_length=1, max_length=64)


def create_router(uc) -> APIRouter:
    """Return an APIRouter with a single POST endpoint.

    ``uc`` must have ``async def execute(*, name: str) -> KnowledgeBase``.
    """

    router = APIRouter()

    @router.post("/v1/knowledge-bases:create")
    async def create_kb(req: _CreateKBRequest):
        result = await uc.execute(name=req.name)
        return {
            "code": 0,
            "data": {
                "kb_id": result.id,
                "name": result.name,
                "created_at": result.created_at.isoformat(),
            },
            "message": "ok",
        }

    return router
