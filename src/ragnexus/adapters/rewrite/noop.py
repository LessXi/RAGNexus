"""空查询改写适配器 — NoopRewriteProvider。

禁用改写时的直通实现：rewrite 返回原始 query，clear_cache 空实现。
"""

from ragnexus.domain.ports import RewriteResult


class NoopRewriteProvider:
    """空查询改写提供者 — 禁用改写时的直通实现。

    rewrite 返回 RewriteResult（original=rewritten=query, needs_rewrite=False），
    clear_cache 空实现（无缓存可清）。
    """

    async def rewrite(
        self,
        *,
        query: str,
        kb_ids: list[str],
    ) -> RewriteResult:
        """直通返回原始 query，不做任何改写。"""
        return RewriteResult(
            original_query=query,
            rewritten_query=query,
            needs_rewrite=False,
            reason="禁用改写，直通",
        )

    async def clear_cache(self, kb_id: str) -> None:
        """空实现 — 无缓存可清。"""
        pass
