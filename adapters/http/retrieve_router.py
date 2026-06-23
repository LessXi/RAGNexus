"""Factory: retrieve_router — POST /v1/rag:retrieve."""

from fastapi import APIRouter
from pydantic import BaseModel, Field


class _RetrieveRequest(BaseModel):
    model_config = {"extra": "forbid"}
    query: str = Field(...)
    kb_ids: list[str] = Field(...)
    top_k: int = 5


def create_router(uc) -> APIRouter:
    """Return an APIRouter with a single POST endpoint.

    ``uc`` must have ``async def execute(
        *, query: str, kb_ids: list[str], top_k: int,
    ) -> list[SearchHit]``.
    """

    router = APIRouter()

    @router.post("/v1/rag:retrieve")
    async def retrieve(req: _RetrieveRequest):
        hits = await uc.execute(
            query=req.query,
            kb_ids=req.kb_ids,
            top_k=req.top_k,
        )
        return {
            "code": 0,
            "data": {
                "total": len(hits),
                "hits": [
                    {
                        "chunk_id": h.chunk_id,
                        "kb_id": h.kb_id,
                        "doc_id": h.doc_id,
                        "score": round(h.score, 6),
                        "text": h.text,
                        "metadata": h.metadata,
                    }
                    for h in hits
                ],
            },
            "message": "ok",
        }

    return router
