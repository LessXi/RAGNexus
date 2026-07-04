"""工厂函数: retrieve_router — POST /v1/rag:retrieve。"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ragnexus.domain.models import SearchHit


class _RerankOptions(BaseModel):
    """重排可选项 — 控制是否启用重排及保留数量。"""

    enabled: bool = False
    top_n: int = Field(default=5, ge=1, le=20)


class _RetrieveRequest(BaseModel):
    """检索请求体 — 支持多路召回 + RRF 融合 + 可选重排。"""

    model_config = {"extra": "forbid"}
    query: str = Field(...)
    kb_ids: list[str] = Field(...)
    top_k: int = Field(default=5, ge=1, le=50)
    mode: Literal["vector", "bm25", "hybrid"] = "hybrid"
    vector_top_k: int = Field(default=20, ge=1, le=200)
    bm25_top_k: int = Field(default=20, ge=1, le=200)
    rrf_k: int = Field(default=60, ge=1, le=200)
    rerank: _RerankOptions | None = None


def _serialize_hit(h: SearchHit) -> dict:
    """将 SearchHit 序列化为 API 响应格式。

    - 用 .get() 提取评分字段（不删除，metadata 保持完整）
    - file_name → title 映射
    """
    serialized: dict = {
        "chunk_id": h.chunk_id,
        "kb_id": h.kb_id,
        "doc_id": h.doc_id,
        "score": round(h.score, 6),
        "text": h.text,
        "metadata": h.metadata,
        "title": h.metadata.get("filename", ""),
    }
    # 提取评分字段（有值时输出，不回退到 str.lower 判空）
    if (vs := h.metadata.get("_vector_score")) is not None:
        serialized["vector_score"] = vs
    if (bs := h.metadata.get("_bm25_score")) is not None:
        serialized["bm25_score"] = bs
    if (rs := h.metadata.get("_rerank_score")) is not None:
        serialized["rerank_score"] = rs
    return serialized


def create_router(uc) -> APIRouter:
    """返回含单个 POST 端点的 APIRouter。

    ``uc`` 必须提供 ``async def execute(
        *, query: str, kb_ids: list[str], top_k: int,
        mode: str | None = None,
        vector_top_k: int | None = None,
        bm25_top_k: int | None = None,
        rrf_k: int = 60,
        rerank_enabled: bool | None = None,
        rerank_top_n: int = 5,
    ) -> RetrieveResult``。
    """

    router = APIRouter()

    @router.post("/v1/rag:retrieve")
    async def retrieve(req: _RetrieveRequest):
        # 解析 rerank 选项
        rerank_enabled = req.rerank.enabled if req.rerank else None
        rerank_top_n = req.rerank.top_n if req.rerank else 5

        result = await uc.execute(
            query=req.query,
            kb_ids=req.kb_ids,
            top_k=req.top_k,
            mode=req.mode,
            vector_top_k=req.vector_top_k,
            bm25_top_k=req.bm25_top_k,
            rrf_k=req.rrf_k,
            rerank_enabled=rerank_enabled,
            rerank_top_n=rerank_top_n,
        )
        return {
            "code": 0,
            "data": {
                "hits": [_serialize_hit(h) for h in result.hits],
                "meta": {
                    "total": result.total,
                    "latency_ms": result.latency_ms,
                    "mode": result.mode,
                    "vector_count": result.vector_count,
                    "bm25_count": result.bm25_count,
                    "fused_count": result.fused_count,
                    "rerank_model": result.rerank_model,
                    "degraded": result.degraded,
                    "degraded_reason": result.degraded_reason,
                },
            },
            "message": "ok",
        }

    return router
