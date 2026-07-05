"""RetrieveUseCase — 校验查询、嵌入向量、搜索向量库、异步记录日志。"""

import asyncio
import os
import time

from ragnexus.adapters.rewrite.pipeline import QueryPipeline
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.core.logger import logger
from ragnexus.domain.models import RetrieveResult, SearchHit
from ragnexus.domain.ports import (
    EmbedderPort,
    KeywordSearchPort,
    KnowledgeBasePort,
    QueryProcessResult,
    RerankPort,
    RetrieveLogPort,
    RewritePort,
    VectorStorePort,
)
from ragnexus.domain.retrieval.fusion import rrf_fuse


class RetrieveUseCase:
    """跨知识库按查询搜索 chunk。"""

    def __init__(
        self,
        kb_repo: KnowledgeBasePort,
        embedder: EmbedderPort,
        store: VectorStorePort,
        log_port: RetrieveLogPort,
        reranker: RerankPort,
        rewriter: RewritePort | None = None,
        pipeline: QueryPipeline | None = None,
        keyword_store: KeywordSearchPort | None = None,
        candidate_k: int = 20,
        retrieval_mode: str = "hybrid",
    ) -> None:
        self._kb_repo = kb_repo
        self._embedder = embedder
        self._store = store
        self._log_port = log_port
        self._reranker = reranker
        self._rewriter = rewriter
        self._pipeline = pipeline
        self._keyword_store = keyword_store
        self._candidate_k = candidate_k
        self._retrieval_mode = retrieval_mode
        self._background_tasks: set[asyncio.Task] = set()

    async def execute(
        self,
        query: str,
        kb_ids: list[str],
        tenant_id: str,
        top_k: int = 5,
        mode: str | None = None,
        vector_top_k: int | None = None,
        bm25_top_k: int | None = None,
        rrf_k: int = 60,
        rerank_enabled: bool | None = None,
        rerank_top_n: int = 5,
        query_options: dict | None = None,
    ) -> RetrieveResult:
        """执行检索：校验 → 改写 → 双路召回 → RRF 融合 → 重排 → 返回 RetrieveResult。

        参数:
            query: 用户查询字符串
            kb_ids: 目标知识库 ID 列表
            top_k: 最终返回的 chunk 数量（传给 reranker.rerank top_n 参数）
            mode: 检索模式 ("hybrid"|"vector"|"bm25")，None 用 self._retrieval_mode
            vector_top_k: 向量召回候选数，None 用 self._candidate_k
            bm25_top_k: BM25 召回候选数，None 用 self._candidate_k
            rrf_k: RRF 融合参数 k
            rerank_enabled: 是否启用重排，None 根据 self._reranker 类型自动判断
            rerank_top_n: 重排后保留数（传入 reranker.rerank top_n 参数）

        返回:
            RetrieveResult，包含 hits、计数统计、延迟和降级标记
        """
        # --- 解析默认值 ---
        _mode = self._retrieval_mode if mode is None else mode
        _vector_top_k = self._candidate_k if vector_top_k is None else vector_top_k
        _bm25_top_k = self._candidate_k if bm25_top_k is None else bm25_top_k
        _rerank_enabled = (
            getattr(self._reranker, "model_name", None) is not None
            if rerank_enabled is None
            else rerank_enabled
        )

        # 1. Validate inputs（统一使用 stripped query，避免空格进入向量和日志）
        query = query.strip()
        if not query or len(query) > 2000:
            raise AppError(ErrorCode.PARAM_ERROR, "query 不能为空且长度不能超过 2000")
        if not kb_ids or len(kb_ids) > 5:
            raise AppError(ErrorCode.PARAM_ERROR, "kb_ids 不能为空且最多 5 个")
        if not (1 <= top_k <= 50):
            raise AppError(ErrorCode.PARAM_ERROR, "top_k 必须在 1-50 之间")

        # 2. Validate all KBs exist
        for kb_id in kb_ids:
            if not await self._kb_repo.exists(kb_id):
                raise AppError(ErrorCode.NOT_FOUND, f"知识库不存在: {kb_id}")

        # 3. Validate all KBs belong to current tenant
        await self.validate_kb_ownership(kb_ids, tenant_id)
        # 3.5 组装 KB 上下文（用于查询改写和词表扩展）
        primary_kb = await self._kb_repo.get(kb_ids[0])
        kb_context: dict = {}
        synonyms: list[dict] | None = None
        if primary_kb:
            kb_context = {
                "name": primary_kb.name,
                "description": getattr(primary_kb, "description", ""),
            }
            kb_settings = getattr(primary_kb, "settings", {}) or {}
            if isinstance(kb_settings, dict):
                kb_context["rewrite_hint"] = kb_settings.get("rewrite_hint", "")
                synonyms = kb_settings.get("synonyms")

        # --- 退化检测：ES 不可用 + hybrid 模式 → 降级为纯向量 ---
        degraded = False
        degraded_reason: str | None = None
        if self._keyword_store is None and _mode == "hybrid":
            degraded = True
            degraded_reason = "ES 不可用，降级为纯向量检索"
            _mode = "vector"

        # 3. Retrieve — 查询改写 → 双 embedding → 并行召回 → RRF 融合 → 重排
        original_query = query  # 保存原始 query，用于 rerank（相关性判断）和日志
        t0 = time.perf_counter()
        hits: list[SearchHit] = []
        kw_hits: list[SearchHit] = []
        vec_hits_raw: list[SearchHit] = []
        vector_latency_ms = 0
        keyword_latency_ms = 0
        rrf_pool_size = 0
        try:
            if self._pipeline is not None:
                # 全局默认来自环境变量 QUERY_REWRITE_ENABLED，请求级 query_options.enabled 优先
                env_default = (
                    os.getenv("QUERY_REWRITE_ENABLED", "false").lower() == "true"
                )
                enabled = (
                    query_options.get("enabled", env_default)
                    if query_options
                    else env_default
                )
                process_result = await self._pipeline.process(
                    raw_query=query,
                    kb_ids=kb_ids,
                    kb_context=kb_context,
                    synonyms=synonyms,
                    enabled=enabled,
                )
                search_query = process_result.search_query
                query_processing = _serialize_query_processing(process_result)
            elif self._rewriter is not None:
                rewrite_result = await self._rewriter.rewrite(
                    query=query, kb_ids=kb_ids
                )
                search_query = rewrite_result.effective_query
                query_processing = None
            else:
                search_query = query
                query_processing = None

            # 3b. 双 embedding: 改写后 query → 向量搜索，原始 query → rerank 缓存匹配
            vectors = await self._embedder.embed([search_query, original_query])
            search_vector = vectors[0]  # embed(改写后) → 向量搜索
            original_vector = vectors[1]  # embed(原始) → rerank 缓存匹配

            use_vector = _mode in ("hybrid", "vector")
            use_bm25 = _mode in ("hybrid", "bm25") and self._keyword_store is not None

            # 3c. 并行召回：向量 + BM25 双路
            t_vec = time.perf_counter()
            tasks = []
            if use_vector:
                tasks.append(
                    self._store.search_by_vector(search_vector, _vector_top_k, kb_ids)
                )
            if use_bm25:
                tasks.append(
                    self._keyword_store.search_by_keyword(  # type: ignore[union-attr]
                        kb_ids[0], original_query, _bm25_top_k
                    )
                )

            results = await asyncio.gather(*tasks, return_exceptions=True)
            gather_latency_ms = int((time.perf_counter() - t_vec) * 1000)
            vector_latency_ms = gather_latency_ms
            keyword_latency_ms = gather_latency_ms

            idx = 0
            if use_vector:
                vec_result = results[idx]
                vec_hits_raw = [] if isinstance(vec_result, Exception) else vec_result
                # 分数标记：向量分写入 metadata
                for hit in vec_hits_raw:
                    hit.metadata["_vector_score"] = hit.score
                idx += 1
            if use_bm25:
                kw_result = results[idx]
                kw_hits = [] if isinstance(kw_result, Exception) else kw_result
                # 分数标记：BM25 分写入 metadata
                for kw_hit in kw_hits:
                    kw_hit.metadata["_bm25_score"] = kw_hit.score
            # BIZ_EVENT: 关键词检索日志
            if use_bm25:
                try:
                    kw_failed = isinstance(kw_result, Exception)
                    logger.info(
                        "",
                        extra={
                            "event_type": "BIZ_EVENT",
                            "event": (
                                "keyword_search_fail"
                                if kw_failed
                                else "keyword_search_done"
                            ),
                            "kb_ids": kb_ids,
                            "query": original_query[:200],
                            "hit_count": len(kw_hits),
                            "latency_ms": keyword_latency_ms,
                        },
                    )
                except Exception:
                    pass

            # 3d. RRF 融合
            hits = rrf_fuse(vec_hits_raw, kw_hits, k=rrf_k)
            rrf_pool_size = len(hits)  # 融合后去重数

            # 3e. 重排：用原始 query + 原始 query embedding（对齐 BM25 和缓存）
            reranker_model: str | None = None
            if _rerank_enabled:
                hits = await self._reranker.rerank(
                    query=original_query,
                    query_vector=original_vector,
                    kb_ids=kb_ids,
                    chunks=hits,
                    top_n=rerank_top_n,
                )
                reranker_model = getattr(self._reranker, "model_name", None)
            else:
                hits = hits[:rerank_top_n]

            # --- 计时：return 前计算 latency_ms ---
            latency_ms = int((time.perf_counter() - t0) * 1000)

            return RetrieveResult(
                hits=hits,
                total=len(hits),
                latency_ms=latency_ms,
                mode=_mode,
                vector_count=len(vec_hits_raw),
                bm25_count=len(kw_hits),
                fused_count=rrf_pool_size,
                rerank_model=reranker_model,
                degraded=degraded,
                degraded_reason=degraded_reason,
                query_processing=query_processing,
            )
        finally:
            # --- 仅保留资源清理：fire-and-forget 日志 ---
            final_latency_ms = int((time.perf_counter() - t0) * 1000)
            task = asyncio.create_task(
                self._safe_log(
                    query=query,
                    kb_ids=kb_ids,
                    top_k=top_k,
                    hit_count=len(hits),
                    latency_ms=final_latency_ms,
                    retrieval_mode=_mode,
                    vector_hit_count=len(vec_hits_raw),
                    keyword_hit_count=len(kw_hits),
                    rrf_pool_size=rrf_pool_size,
                    vector_latency_ms=vector_latency_ms,
                    keyword_latency_ms=keyword_latency_ms,
                )
            )
            task.add_done_callback(self._background_tasks.discard)
            self._background_tasks.add(task)

    async def _safe_log(
        self,
        query: str,
        kb_ids: list[str],
        top_k: int,
        hit_count: int,
        latency_ms: int,
        retrieval_mode: str = "hybrid",
        vector_hit_count: int = 0,
        keyword_hit_count: int = 0,
        rrf_pool_size: int = 0,
        vector_latency_ms: int = 0,
        keyword_latency_ms: int = 0,
    ) -> None:
        """Fire-and-forget log call — 异常被捕获并在 debug 级别记录，不中断主流程。"""
        try:
            await self._log_port.log(
                query=query,
                kb_ids=kb_ids,
                top_k=top_k,
                hit_count=hit_count,
                latency_ms=latency_ms,
            )
        except Exception:
            logger.debug("retrieve 日志写入失败", exc_info=True)

        # BIZ_EVENT: 检索完成（用户可感知结果 + 外部副作用）
        try:
            logger.info(
                "",
                extra={
                    "event_type": "BIZ_EVENT",
                    "event": "retrieve_completed",
                    "kb_ids": kb_ids,
                    "top_k": top_k,
                    "hit_count": hit_count,
                    "latency_ms": latency_ms,
                    "retrieval_mode": retrieval_mode,
                    "vector_hit_count": vector_hit_count,
                    "keyword_hit_count": keyword_hit_count,
                    "rrf_pool_size": rrf_pool_size,
                    "vector_latency_ms": vector_latency_ms,
                    "keyword_latency_ms": keyword_latency_ms,
                },
            )
        except Exception:
            logger.debug("BIZ_EVENT 日志写入失败", exc_info=True)

    async def validate_kb_ownership(self, kb_ids: list[str], tenant_id: str) -> None:
        """校验 kb_ids 是否全部属于指定租户，不匹配则抛出 FORBIDDEN。"""
        unique_ids = set(kb_ids)
        if not unique_ids:
            return
        count = await self._kb_repo.pool.fetchval(
            "SELECT COUNT(*) FROM knowledge_bases WHERE id = ANY($1) AND tenant_id = $2",
            list(unique_ids),
            tenant_id,
        )
        if count != len(unique_ids):
            raise AppError(
                ErrorCode.FORBIDDEN,
                f"部分知识库不属于当前租户（请求 {len(unique_ids)} 个，归属 {count} 个）",
            )


def _serialize_query_processing(result: QueryProcessResult) -> dict:
    """将 QueryProcessResult 序列化为 query_processing dict。"""
    return {
        "raw_query": result.raw_query,
        "effective_query": result.effective_query,
        "search_query": result.search_query,
        "needs_rewrite": result.needs_rewrite,
        "strategy": result.strategy,
        "rewrite_latency_ms": result.rewrite_latency_ms,
        "degraded": result.degraded,
        "synonym_applied": result.synonym_applied,
        "synonym_expansions": result.synonym_expansions,
    }
