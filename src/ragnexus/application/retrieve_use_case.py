"""RetrieveUseCase — 校验查询、嵌入向量、搜索向量库、异步记录日志。"""

import asyncio
import contextlib
import time

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.core.logger import logger
from ragnexus.domain.models import SearchHit
from ragnexus.domain.ports import (
    EmbedderPort,
    KnowledgeBasePort,
    RerankPort,
    RetrieveLogPort,
    RewritePort,
    VectorStorePort,
)


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
        candidate_multiplier: int = 1,
        min_candidates: int = 0,
    ) -> None:
        self._kb_repo = kb_repo
        self._embedder = embedder
        self._store = store
        self._log_port = log_port
        self._reranker = reranker
        self._rewriter = rewriter
        self._candidate_multiplier = candidate_multiplier
        self._min_candidates = min_candidates
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

        # 3. Retrieve — 查询改写 → 向量召回 → 重排
        original_query = query  # 保存原始 query，用于 rerank（相关性判断）和日志
        t0 = time.perf_counter()
        hits: list[SearchHit] = []
        try:
            # 3a. 查询改写（在 embed 之前，优化口语化/模糊 query）
            rewrite_result = await self._rewriter.rewrite(query=query, kb_ids=kb_ids)
            search_query = rewrite_result.rewritten_query

            # 3b. embed 用改写后的 query
            vectors = await self._embedder.embed([search_query])
            query_vector = vectors[0]

            # 计算候选数：重排前多召回，确保 RerankPort 有充足候选
            candidate_k = max(
                top_k * self._candidate_multiplier,
                top_k + self._min_candidates,
            )

            # 向量召回（使用 candidate_k）
            hits = await self._store.search_by_vector(query_vector, candidate_k, kb_ids)

            # 重排：启用时 LLMRerankProvider 重排序，禁用时 NoopRerankProvider 直通
            # rerank 用原始 query 做相关性判断，query_vector 为改写后的向量
            hits = await self._reranker.rerank(
                query=original_query,
                query_vector=query_vector,
                kb_ids=kb_ids,
                chunks=hits,
                top_n=top_k,
            )

            return hits
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            hit_count = len(hits)
            task = asyncio.create_task(
                self._safe_log(query, kb_ids, top_k, hit_count, latency_ms)
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
                },
            )
        except Exception:
            logger.debug("BIZ_EVENT 日志写入失败", exc_info=True)
