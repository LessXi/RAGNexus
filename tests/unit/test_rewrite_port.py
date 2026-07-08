"""RewritePort Protocol 单元测试。

验证 RewritePort 接口定义正确，以及结构性子类型兼容性。
适配 QueryProcessResult（10 字段 + kb_contexts 传参）。
"""

from __future__ import annotations

import asyncio
from dataclasses import is_dataclass
from typing import Protocol

from ragnexus.domain.ports import QueryProcessResult, RewritePort


class TestQueryProcessResult:
    """QueryProcessResult dataclass 测试 — 10 字段完整性。"""

    def test_query_process_result_is_dataclass(self) -> None:
        """QueryProcessResult 应为 dataclass。"""
        assert is_dataclass(QueryProcessResult)

    def test_query_process_result_all_10_fields(self) -> None:
        """QueryProcessResult 应有全部 10 个字段，包括 3 段 query + 元数据。"""
        result = QueryProcessResult(
            raw_query="什么是 RAG",
            effective_query="检索增强生成（RAG）是什么",
            search_query="检索增强生成 (RAG) 是什么 向量检索",
            needs_rewrite=True,
            strategy="rewrite",
            rewrite_latency_ms=350,
            degraded=False,
            degraded_reason=None,
            synonym_applied=True,
            synonym_expansions=["向量检索", "知识库"],
        )

        # 三段 query
        assert result.raw_query == "什么是 RAG"
        assert result.effective_query == "检索增强生成（RAG）是什么"
        assert result.search_query == "检索增强生成 (RAG) 是什么 向量检索"
        # 元数据
        assert result.needs_rewrite is True
        assert result.strategy == "rewrite"
        assert result.rewrite_latency_ms == 350
        assert result.degraded is False
        assert result.degraded_reason is None
        assert result.synonym_applied is True
        assert result.synonym_expansions == ["向量检索", "知识库"]

    def test_query_process_result_degraded_behavior(self) -> None:
        """降级时 effective_query == raw_query, degraded=True, degraded_reason 非空。"""
        result = QueryProcessResult(
            raw_query="检索增强生成",
            effective_query="检索增强生成",
            search_query="检索增强生成",
            needs_rewrite=False,
            strategy="rewrite",
            rewrite_latency_ms=0,
            degraded=True,
            degraded_reason="LLM 调用失败: TimeoutError: 请求超时",
            synonym_applied=False,
            synonym_expansions=[],
        )

        assert result.raw_query == result.effective_query
        assert result.needs_rewrite is False
        assert result.degraded is True
        assert "超时" in result.degraded_reason

    def test_query_process_result_noop_strategy(self) -> None:
        """禁用改写时 strategy="noop", 三阶段相同。"""
        result = QueryProcessResult(
            raw_query="检索增强生成",
            effective_query="检索增强生成",
            search_query="检索增强生成",
            needs_rewrite=False,
            strategy="noop",
            rewrite_latency_ms=0,
            degraded=False,
            degraded_reason=None,
            synonym_applied=False,
            synonym_expansions=[],
        )

        assert result.strategy == "noop"
        assert result.raw_query == result.effective_query == result.search_query
        assert result.needs_rewrite is False
        assert result.degraded is False


class TestRewritePortProtocol:
    """RewritePort Protocol 签名与结构性子类型测试。"""

    def test_rewrite_port_is_protocol(self) -> None:
        """RewritePort 应是 typing.Protocol 的子类。"""
        assert issubclass(RewritePort, Protocol)

    def test_rewrite_method_signature(self) -> None:
        """rewrite 方法签名：keyword-only 参数，返回 QueryProcessResult，包含 kb_contexts。"""
        import inspect

        sig = inspect.signature(RewritePort.rewrite)

        params = list(sig.parameters.values())
        param_names = [p.name for p in params]

        # self + 3 keyword-only 参数（含 kb_contexts）
        assert param_names == [
            "self",
            "query",
            "kb_ids",
            "kb_contexts",
        ], f"参数名不匹配: {param_names}"

        for p in params[1:]:  # 跳过 self
            assert (
                p.kind == inspect.Parameter.KEYWORD_ONLY
            ), f"{p.name} 应为 KEYWORD_ONLY，实际: {p.kind}"

        # kb_context 应为可选参数
        assert params[-1].default is None, "kb_contexts 默认值应为 None"

        # 验证返回类型注解为 QueryProcessResult
        assert (
            sig.return_annotation == QueryProcessResult
        ), f"返回类型应为 QueryProcessResult，实际: {sig.return_annotation}"

    def test_clear_cache_method_signature(self) -> None:
        """clear_cache 方法签名：kb_id: str → None。"""
        import inspect

        sig = inspect.signature(RewritePort.clear_cache)

        params = list(sig.parameters.values())
        assert len(params) == 2  # self + kb_id
        assert params[0].name == "self"
        assert params[1].name == "kb_id"
        assert params[1].annotation is str
        assert sig.return_annotation is None

    def test_minimal_implementation_satisfies_protocol(self) -> None:
        """一个最小实现类应满足 RewritePort 协议结构。

        Python Protocol 使用静态结构子类型（pyright/mypy），运行时不需要
        @runtime_checkable。这里通过实际调用来验证行为正确性。
        """

        class _MinimalRewriter:
            """最小实现 — 原样返回查询，不做改写，支持 kb_contexts 传参。"""

            async def rewrite(
                self,
                *,
                query: str,
                kb_ids: list[str],
                kb_contexts: list[dict] | None = None,
            ) -> QueryProcessResult:
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
                pass

        instance = _MinimalRewriter()

        async def _run_rewrite() -> QueryProcessResult:
            return await instance.rewrite(
                query="什么是 RAG",
                kb_ids=["kb1", "kb2"],
            )

        result = asyncio.run(_run_rewrite())

        assert result.raw_query == "什么是 RAG"
        assert result.effective_query == "什么是 RAG"
        assert result.search_query == "什么是 RAG"
        assert result.needs_rewrite is False
        assert result.strategy == "noop"
        assert result.degraded is False

        async def _run_rewrite_with_context() -> QueryProcessResult:
            return await instance.rewrite(
                query="测试",
                kb_ids=["kb1"],
                kb_contexts=[{"name": "测试知识库"}],
            )

        ctx_result = asyncio.run(_run_rewrite_with_context())
        assert ctx_result.raw_query == "测试"
        # kb_contexts 不影响结果，但应被正确接收

        # 验证 clear_cache 也可正常调用
        async def _run_clear() -> None:
            await instance.clear_cache(kb_id="kb1")

        asyncio.run(_run_clear())  # 不应抛异常
