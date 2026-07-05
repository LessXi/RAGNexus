"""查询处理流水线 — 串联改写+词表扩展，输出三阶段结果。

QueryPipeline 是查询处理的核心编排器：
1. raw_query → rewrite() → effective_query
2. effective_query → expand() → search_query

负责降级策略和异常处理。
"""

from __future__ import annotations

from ragnexus.adapters.rewrite.synonym_expander import SynonymExpander
from ragnexus.domain.ports import QueryProcessResult, RewritePort


class QueryPipeline:
    """查询处理流水线 — 串联改写+词表扩展，输出三阶段结果。

    raw_query → rewrite() → effective_query → expand() → search_query
    """

    def __init__(self, rewriter: RewritePort, expander: SynonymExpander) -> None:
        """初始化流水线。

        参数:
            rewriter: 查询改写提供者（LLM 或 Noop）。
            expander: 词表扩展器。
        """
        self.rewriter = rewriter
        self.expander = expander

    async def process(
        self,
        raw_query: str,
        kb_ids: list[str],
        kb_context: dict | None = None,
        synonyms: list[dict] | None = None,
        enabled: bool = True,
    ) -> QueryProcessResult:
        """执行查询处理流水线。

        参数:
            raw_query: 用户原始查询。
            kb_ids: 知识库 ID 列表，透传给 rewriter.rewrite()。
            kb_context: 知识库上下文，透传给 rewriter.rewrite()。
            synonyms: 词表列表，透传给 expander.expand()。
            enabled: False 时跳过改写和扩展，直接返回 noop 结果。

        返回:
            QueryProcessResult 包含三阶段查询及处理元数据。
        """
        if not enabled:
            return QueryProcessResult(
                raw_query=raw_query,
                effective_query=raw_query,
                search_query=raw_query,
                needs_rewrite=False,
                strategy="noop",
                rewrite_latency_ms=0,
                degraded=False,
                degraded_reason=None,
                synonym_applied=False,
                synonym_expansions=[],
            )

        # Step 1: 调用 rewriter.rewrite()
        try:
            result = await self.rewriter.rewrite(
                query=raw_query,
                kb_ids=kb_ids,
                kb_context=kb_context,
            )
        except Exception as exc:
            # rewrite() 抛异常 → 降级返回
            return QueryProcessResult(
                raw_query=raw_query,
                effective_query=raw_query,
                search_query=raw_query,
                needs_rewrite=False,
                strategy="rewrite",
                rewrite_latency_ms=0,
                degraded=True,
                degraded_reason=str(exc),
                synonym_applied=False,
                synonym_expansions=[],
            )

        # Step 2: 词表扩展（若提供 synonyms）
        if synonyms:
            search_query, synonym_applied, expansions = self.expander.expand(
                result.effective_query, synonyms
            )
            result.search_query = search_query
            result.synonym_applied = synonym_applied
            result.synonym_expansions = expansions

        return result
