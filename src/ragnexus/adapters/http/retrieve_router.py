"""工厂函数: retrieve_router — POST /v1/rag:retrieve。

含 plan 策略层：profile 校验 → profile 展开 → QPS 限流 → 检索 → 日计数 +1。
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ragnexus.core.auth import TenantContext
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import SearchHit
from ragnexus.tenant.plan_resolver import resolve_plan
from ragnexus.tenant.retrieve_presets import RETRIEVE_PROFILE_PRESETS


class _RerankOptions(BaseModel):
    """重排可选项 — 控制是否启用重排及保留数量。"""

    enabled: bool = False
    top_n: int = Field(default=5, ge=1, le=20)


class _QueryOptions(BaseModel):
    """查询处理可选项 — 控制改写和词表扩展。"""

    enabled: bool = True
    strategy: str = "rewrite"


class _RetrieveRequest(BaseModel):
    """检索请求体 — 支持多路召回 + RRF 融合 + 可选重排 + profile 预设。"""

    model_config = {"extra": "forbid"}
    query: str = Field(...)
    kb_ids: list[str] = Field(...)
    top_k: int = Field(default=5, ge=1, le=50)
    mode: Literal["vector", "bm25", "hybrid"] = "hybrid"
    vector_top_k: int = Field(default=20, ge=1, le=200)
    bm25_top_k: int = Field(default=20, ge=1, le=200)
    rrf_k: int = Field(default=60, ge=1, le=200)
    rerank: _RerankOptions | None = None
    query_options: _QueryOptions | None = None
    profile: Literal["speed", "balanced", "quality", "custom"] | None = None


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


def create_router(
    uc, get_current_tenant, rate_limiter=None, quota_svc=None
) -> APIRouter:
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
    async def retrieve(
        req: _RetrieveRequest,
        current_tenant: TenantContext = Depends(get_current_tenant),
    ):
        # ── Step 1: 解析 plan ───────────────────────────────────────────
        plan_ctx = resolve_plan(current_tenant.plan)

        # ── Step 2: profile 校验（默认 balanced）─────────────────────────
        profile_name: str = req.profile or "balanced"
        if profile_name not in plan_ctx.features.allowed_profiles:
            raise AppError(
                ErrorCode.FEATURE_NOT_ALLOWED,
                f"当前套餐 {current_tenant.plan} 不支持检索预设 {profile_name}",
            )

        # ── Step 3: profile 展开 ────────────────────────────────────────
        if profile_name != "custom":
            preset = RETRIEVE_PROFILE_PRESETS[profile_name]
            effective_mode = preset["mode"]
            effective_top_k = preset["top_k"]
            effective_rerank_enabled = preset.get("rerank_enabled", False)
            effective_rerank_top_n = preset.get("rerank_top_n", 5)
            effective_query_options_dict = preset.get("query_options")
        else:
            # custom: 用请求参数，逐项校验 plan ceiling
            effective_mode = req.mode
            effective_top_k = req.top_k
            effective_rerank_enabled = req.rerank.enabled if req.rerank else None
            effective_rerank_top_n = req.rerank.top_n if req.rerank else 5
            effective_query_options_dict = (
                req.query_options.model_dump(exclude_unset=True)
                if req.query_options
                else None
            )
            if effective_rerank_enabled and not plan_ctx.features.rerank_allowed:
                raise AppError(ErrorCode.FEATURE_NOT_ALLOWED, "当前套餐不支持 rerank")
            if effective_mode == "hybrid" and not plan_ctx.features.hybrid_allowed:
                raise AppError(
                    ErrorCode.FEATURE_NOT_ALLOWED, "当前套餐不支持 hybrid 检索"
                )
            if (
                effective_query_options_dict
                and effective_query_options_dict.get("enabled")
                and not plan_ctx.features.query_rewrite_allowed
            ):
                raise AppError(
                    ErrorCode.FEATURE_NOT_ALLOWED, "当前套餐不支持 query 改写"
                )

        # ── Step 4: QPS + 日配额限流 ────────────────────────────────────
        if rate_limiter:
            await rate_limiter.check_retrieve(
                current_tenant.tenant_id, current_tenant.plan
            )

        # ── Step 5: 调用检索管道 ──────────────────────────────────────
        result = await uc.execute(
            query=req.query,
            kb_ids=req.kb_ids,
            tenant_id=current_tenant.tenant_id,
            top_k=effective_top_k,
            mode=effective_mode,
            vector_top_k=req.vector_top_k,
            bm25_top_k=req.bm25_top_k,
            rrf_k=req.rrf_k,
            rerank_enabled=effective_rerank_enabled,
            rerank_top_n=effective_rerank_top_n,
            query_options=effective_query_options_dict,
        )

        # ── Step 6: 日计数 +1（仅在检索成功后）─────────────────────────
        if rate_limiter:
            await rate_limiter.record_retrieve_success(current_tenant.tenant_id)

        # ── 构建 query_processing 字段 ─────────────────────────────────
        qp = result.query_processing
        query_processing = None
        if qp and (qp.get("strategy") != "noop" or qp.get("synonym_applied")):
            query_processing = qp

        return {
            "code": 0,
            "data": {
                "query": req.query,
                "hits": [_serialize_hit(h) for h in result.hits],
                "meta": {
                    "query_processing": query_processing,
                    "total": result.total,
                    "latency_ms": result.latency_ms,
                    "mode": result.mode,
                    "vector_count": result.vector_count,
                    "bm25_count": result.bm25_count,
                    "fused_count": result.fused_count,
                    "rerank_model": result.rerank_model,
                    "degraded": result.degraded,
                    "degraded_reason": result.degraded_reason,
                    "tenant_policy": {
                        "plan": current_tenant.plan,
                        "retrieve_profile": profile_name,
                        "effective_mode": effective_mode,
                        "effective_rerank": effective_rerank_enabled or False,
                        "effective_query_rewrite": bool(
                            effective_query_options_dict
                            and effective_query_options_dict.get("enabled")
                        ),
                    },
                },
            },
            "message": "ok",
        }

    return router
