"""RetrieveUseCase — validates query, embeds, searches vector store, logs asynchronously."""

import asyncio
import time

from domain.errors import ValidationError, NotFoundError
from domain.models import SearchHit
from domain.ports import EmbedderPort, VectorStorePort, KnowledgeBasePort, RetrieveLogPort


class RetrieveUseCase:
    """Search chunks by query across knowledge bases."""

    def __init__(
        self,
        kb_repo: KnowledgeBasePort,
        embedder: EmbedderPort,
        store: VectorStorePort,
        log_port: RetrieveLogPort,
    ) -> None:
        self._kb_repo = kb_repo
        self._embedder = embedder
        self._store = store
        self._log_port = log_port

    async def execute(
        self, query: str, kb_ids: list[str], top_k: int = 5
    ) -> list[SearchHit]:
        # 1. Validate inputs
        stripped = query.strip()
        if not stripped or len(query) > 2000:
            raise ValidationError("query 不能为空且长度不能超过 2000")
        if not kb_ids or len(kb_ids) > 5:
            raise ValidationError("kb_ids 不能为空且最多 5 个")
        if not (1 <= top_k <= 50):
            raise ValidationError("top_k 必须在 1-50 之间")

        # 2. Validate all KBs exist
        for kb_id in kb_ids:
            if not await self._kb_repo.exists(kb_id):
                raise NotFoundError(f"知识库不存在: {kb_id}")

        # 3. Retrieve
        t0 = time.perf_counter()
        hits: list[SearchHit] = []
        try:
            vectors = await self._embedder.embed([query])
            hits = await self._store.search_by_vector(vectors[0], top_k, kb_ids)
            return hits
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            hit_count = len(hits)
            asyncio.create_task(self._safe_log(query, kb_ids, top_k, hit_count, latency_ms))

    async def _safe_log(
        self,
        query: str,
        kb_ids: list[str],
        top_k: int,
        hit_count: int,
        latency_ms: int,
    ) -> None:
        """Fire-and-forget log call — swallow any exception."""
        try:
            await self._log_port.log(
                query=query,
                kb_ids=kb_ids,
                top_k=top_k,
                hit_count=hit_count,
                latency_ms=latency_ms,
            )
        except Exception:
            pass
