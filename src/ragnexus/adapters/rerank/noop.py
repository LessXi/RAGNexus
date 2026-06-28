"""空重排适配器 — NoopRerankProvider。

禁用重排时的直通实现：rerank 返回原始 chunks，clear_cache 空实现。
"""

from ragnexus.domain.models import SearchHit


class NoopRerankProvider:
    """空重排提供者 — 禁用重排时的直通实现。

    rerank 返回原始 chunks（不排序，按 top_n 截断），
    clear_cache 空实现（无缓存可清）。
    """

    async def rerank(
        self,
        *,
        query: str,
        query_vector: list[float],
        kb_ids: list[str],
        chunks: list[SearchHit],
        top_n: int,
    ) -> list[SearchHit]:
        """直通返回原始 chunks（不排序，按 top_n 截断），不做重排。"""
        return chunks[:top_n]

    async def clear_cache(self, kb_id: str) -> None:
        """空实现 — 无缓存可清。"""
        pass
