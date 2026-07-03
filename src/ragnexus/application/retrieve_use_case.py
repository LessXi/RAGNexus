"""RetrieveUseCase — 校验查询、嵌入向量、搜索向量库、异步记录日志。"""

import asyncio
import time

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.core.logger import logger
from ragnexus.domain.models import SearchHit
from ragnexus.domain.ports import (
    EmbedderPort,
    KeywordSearchPort,
    KnowledgeBasePort,
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
        rewriter: RewritePort,
        keyword_store: KeywordSearchPort | None = None,
        candidate_k: int = 20,
        retrieval_mode: str = "hybrid",
    ) -> None:
        self._kb_repo = kb_repo
        self._embedder = embedder
        self._store = store
        self._keyword_store = keyword_store
        self._log_port = log_port
        self._reranker = reranker
        self._rewriter = rewriter
        self._candidate_k = candidate_k
        self._retrieval_mode = retrieval_mode
        self._background_tasks: set[asyncio.Task] = set()

    async def execute(
        self, query: str, kb_ids: list[str], top_k: int = 5
    ) -> list[SearchHit]:
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

        # 3. Retrieve — 查询改写 → 双 embedding → 并行召回 → RRF 融合 → 重排
        original_query = query  # 保存原始 query，用于 rerank（相关性判断）和日志
        t0 = time.perf_counter()
        hits: list[SearchHit] = []
        kw_hits: list[SearchHit] = []
        vector_latency_ms = 0
        keyword_latency_ms = 0
        rrf_pool_size = 0
        mode = self._retrieval_mode  # finally 块可能在 embed 前就触发，提前初始化
        try:
            # 3a. 查询改写（在 embed 之前，优化口语化/模糊 query）
            rewrite_result = await self._rewriter.rewrite(query=query, kb_ids=kb_ids)
            search_query = rewrite_result.rewritten_query

            # 3b. 双 embedding: 改写后 query → 向量搜索，原始 query → rerank 缓存匹配
            vectors = await self._embedder.embed([search_query, original_query])
            search_vector = vectors[0]  # embed(改写后) → 向量搜索
            original_vector = vectors[1]  # embed(原始) → rerank 缓存匹配

            use_vector = mode in ("hybrid", "vector")
            use_bm25 = mode in ("hybrid", "bm25") and self._keyword_store is not None

            # 3c. 并行召回：向量 + BM25 双路
            t_vec = time.perf_counter()
            tasks = []
            if use_vector:
                tasks.append(
                    self._store.search_by_vector(
                        search_vector, self._candidate_k, kb_ids
                    )
                )
            if use_bm25 and self._keyword_store is not None:
                tasks.append(
                    self._keyword_store.search_by_keyword(
                        kb_ids[0], original_query, self._candidate_k
                    )
                )

            results = await asyncio.gather(*tasks, return_exceptions=True)
            gather_latency_ms = int((time.perf_counter() - t_vec) * 1000)
            vector_latency_ms = gather_latency_ms
            keyword_latency_ms = gather_latency_ms

            idx = 0
            if use_vector:
                vec_result = results[idx]
                hits = [] if isinstance(vec_result, Exception) else vec_result
                idx += 1
            if use_bm25:
                kw_result = results[idx]
                kw_hits = [] if isinstance(kw_result, Exception) else kw_result

            # BIZ_EVENT: 关键词检索日志
            if use_bm25:
                try:
                    logger.info(
                        "",
                        extra={
                            "event_type": "BIZ_EVENT",
                            "event": (
                                "keyword_search_done"
                                if not isinstance(kw_result, Exception)
                                else "keyword_search_fail"
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
            hits = rrf_fuse(hits, kw_hits, k=60)
            rrf_pool_size = len(hits)  # 融合后去重数

            # 3e. 重排：用原始 query + 原始 query embedding（对齐 BM25 和缓存）
            hits = await self._reranker.rerank(
                query=original_query,
                query_vector=original_vector,
                kb_ids=kb_ids,
                chunks=hits,
                top_n=top_k,
            )

            return hits
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            hit_count = len(hits)
            task = asyncio.create_task(
                self._safe_log(
                    query=query,
                    kb_ids=kb_ids,
                    top_k=top_k,
                    hit_count=hit_count,
                    latency_ms=latency_ms,
                    retrieval_mode=mode,
                    vector_hit_count=len(hits) if hits else 0,
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
