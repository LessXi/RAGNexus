"""空查询改写适配器 — NoopRewriteProvider。

禁用改写时的直通实现：rewrite 返回原始 query（三阶段 query 均相同），clear_cache 空实现。
"""

from ragnexus.domain.ports import QueryProcessResult


class NoopRewriteProvider:
    """空查询改写提供者 — 禁用改写时的直通实现。

    rewrite 返回 QueryProcessResult（raw=effective=search=query, needs_rewrite=False, strategy="noop"），
    clear_cache 空实现（无缓存可清）。
    """

    async def rewrite(
        self,
        *,
        query: str,
        kb_ids: list[str],
        kb_context: dict | None = None,
    ) -> QueryProcessResult:
        """直通返回原始 query，不做任何改写。

        三阶段 query（raw/effective/search）均等于原始 query，
        strategy 固定为 "noop" 以区别于 LLM 改写路径的 "rewrite"。
        """
        return QueryProcessResult(
            raw_query=query,
            effective_query=query,
            search_query=query,
            needs_rewrite=False,
            strategy="noop",
            rewrite_latency_ms=0,
            degraded=False,
            degraded_reason=None,
            synonym_applied=False,
            synonym_expansions=[],
        )

    async def clear_cache(self, kb_id: str) -> None:
        """空实现 — 无缓存可清。"""
        pass
