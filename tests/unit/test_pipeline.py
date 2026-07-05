"""QueryPipeline 查询处理流水线单元测试。

验证串联改写+词表扩展、noop 模式、异常降级、内部降级透传等场景。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ragnexus.adapters.rewrite.pipeline import QueryPipeline
from ragnexus.adapters.rewrite.synonym_expander import SynonymExpander
from ragnexus.domain.ports import QueryProcessResult, RewritePort


@pytest.fixture
def mock_rewriter() -> AsyncMock:
    """mock RewritePort — 默认返回成功改写结果。"""
    rewriter = AsyncMock(spec=RewritePort)
    rewriter.rewrite.return_value = QueryProcessResult(
        raw_query="今天天气怎么样",
        effective_query="今天天气如何",
        search_query="今天天气如何",
        needs_rewrite=True,
        strategy="rewrite",
        rewrite_latency_ms=42.0,
        degraded=False,
        degraded_reason=None,
        synonym_applied=False,
        synonym_expansions=[],
    )
    return rewriter


@pytest.fixture
def expander() -> SynonymExpander:
    """真实 SynonymExpander 实例。"""
    return SynonymExpander()


@pytest.fixture
def pipeline(mock_rewriter: AsyncMock, expander: SynonymExpander) -> QueryPipeline:
    """注入 mock rewriter + 真实 expander 的 QueryPipeline。"""
    return QueryPipeline(rewriter=mock_rewriter, expander=expander)


class TestQueryPipeline:
    """QueryPipeline.process() 行为测试。"""

    # ── 场景 1: 改写+扩展同开 ─────────────────────────────

    @pytest.mark.asyncio
    async def test_rewrite_and_expand_both_enabled(
        self, pipeline: QueryPipeline, mock_rewriter: AsyncMock
    ) -> None:
        """enabled=true, rewrite 成功, synonyms 有命中 → effective≠raw, search≠effective。"""
        synonyms = [
            {"terms": ["天气"], "expand": ["气候", "气象"]},
        ]

        result = await pipeline.process(
            raw_query="今天天气怎么样",
            kb_ids=["kb-1"],
            kb_context={"name": "天气知识库"},
            synonyms=synonyms,
            enabled=True,
        )

        # rewriter.rewrite 被调用
        mock_rewriter.rewrite.assert_awaited_once_with(
            query="今天天气怎么样",
            kb_ids=["kb-1"],
            kb_context={"name": "天气知识库"},
        )

        # 改写生效
        assert result.raw_query == "今天天气怎么样"
        assert result.effective_query == "今天天气如何"
        assert result.needs_rewrite is True
        assert result.strategy == "rewrite"

        # 扩展生效 — search_query 追加了扩展词
        assert result.effective_query != result.search_query
        assert "气候" in result.search_query
        assert "气象" in result.search_query
        assert result.synonym_applied is True
        assert len(result.synonym_expansions) > 0

    # ── 场景 2: 仅改写 ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_rewrite_only_no_synonyms(
        self, pipeline: QueryPipeline, mock_rewriter: AsyncMock
    ) -> None:
        """enabled=true, synonyms=None → effective≠raw, search==effective。"""
        result = await pipeline.process(
            raw_query="今天天气怎么样",
            kb_ids=["kb-1"],
            kb_context=None,
            synonyms=None,
            enabled=True,
        )

        assert result.raw_query == "今天天气怎么样"
        assert result.effective_query == "今天天气如何"
        # 无扩展 — search 应等于 effective
        assert result.search_query == result.effective_query
        assert result.synonym_applied is False
        assert result.synonym_expansions == []

    # ── 场景 3: enabled=false ────────────────────────────

    @pytest.mark.asyncio
    async def test_disabled_returns_noop(
        self, pipeline: QueryPipeline, mock_rewriter: AsyncMock
    ) -> None:
        """enabled=false → strategy="noop", 三阶段相同, rewriter 未调用。"""
        result = await pipeline.process(
            raw_query="今天天气怎么样",
            kb_ids=["kb-1"],
            enabled=False,
        )

        # rewriter.rewrite 未被调用
        mock_rewriter.rewrite.assert_not_awaited()

        assert result.strategy == "noop"
        assert result.raw_query == "今天天气怎么样"
        assert result.effective_query == result.raw_query
        assert result.search_query == result.raw_query
        assert result.needs_rewrite is False
        assert result.rewrite_latency_ms == 0
        assert result.degraded is False
        assert result.degraded_reason is None
        assert result.synonym_applied is False
        assert result.synonym_expansions == []

    # ── 场景 4: rewrite 异常降级 ─────────────────────────

    @pytest.mark.asyncio
    async def test_rewrite_exception_degraded(
        self, pipeline: QueryPipeline, mock_rewriter: AsyncMock
    ) -> None:
        """rewrite() 抛异常 → degraded=True, effective==raw, 不抛异常。"""
        mock_rewriter.rewrite.side_effect = RuntimeError("LLM 超时")

        # 不应抛异常
        result = await pipeline.process(
            raw_query="今天天气怎么样",
            kb_ids=["kb-1"],
            synonyms=[
                {"terms": ["天气"], "expand": ["气候"]},
            ],
            enabled=True,
        )

        assert result.degraded is True
        assert "LLM 超时" in (result.degraded_reason or "")
        assert result.raw_query == "今天天气怎么样"
        assert result.effective_query == result.raw_query
        assert result.search_query == result.raw_query
        assert result.needs_rewrite is False
        assert result.strategy == "rewrite"
        assert result.synonym_applied is False

    # ── 场景 5: rewrite 内部降级透传 ──────────────────────

    @pytest.mark.asyncio
    async def test_rewrite_internal_degradation_passthrough(
        self, pipeline: QueryPipeline, mock_rewriter: AsyncMock
    ) -> None:
        """rewrite 返回 degraded=True → pipeline 透传 degraded 状态。"""
        mock_rewriter.rewrite.return_value = QueryProcessResult(
            raw_query="今天天气怎么样",
            effective_query="今天天气怎么样",
            search_query="今天天气怎么样",
            needs_rewrite=False,
            strategy="rewrite",
            rewrite_latency_ms=0,
            degraded=True,
            degraded_reason="解析失败: 无效 JSON",
            synonym_applied=False,
            synonym_expansions=[],
        )

        result = await pipeline.process(
            raw_query="今天天气怎么样",
            kb_ids=["kb-1"],
            synonyms=[
                {"terms": ["天气"], "expand": ["气候"]},
            ],
            enabled=True,
        )

        # 透传 degraded 状态
        assert result.degraded is True
        assert result.degraded_reason == "解析失败: 无效 JSON"
        assert result.strategy == "rewrite"
        assert result.effective_query == result.raw_query

        # 扩展仍执行（effective_query 含"天气"命中）
        assert result.synonym_applied is True
        assert "气候" in result.search_query
