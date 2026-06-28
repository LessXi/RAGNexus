"""RewritePort Protocol 单元测试。

验证 RewritePort 接口定义正确，以及结构性子类型兼容性。
"""

from __future__ import annotations

import asyncio
from dataclasses import is_dataclass
from typing import Protocol

from ragnexus.domain.ports import RewritePort, RewriteResult


class TestRewriteResult:
    """RewriteResult dataclass 测试。"""

    def test_rewrite_result_is_dataclass(self) -> None:
        """RewriteResult 应为 dataclass。"""
        assert is_dataclass(RewriteResult)

    def test_rewrite_result_fields(self) -> None:
        """RewriteResult 应有 original_query, rewritten_query, needs_rewrite, reason 四个字段。"""
        result = RewriteResult(
            original_query="什么是 RAG",
            rewritten_query="检索增强生成（RAG）是什么",
            needs_rewrite=True,
            reason="口语化查询，需要改写为更正式的检索语句",
        )

        assert result.original_query == "什么是 RAG"
        assert result.rewritten_query == "检索增强生成（RAG）是什么"
        assert result.needs_rewrite is True
        assert result.reason == "口语化查询，需要改写为更正式的检索语句"

    def test_rewrite_result_default_behavior(self) -> None:
        """不需要改写时 rewritten_query 等于 original_query。"""
        result = RewriteResult(
            original_query="检索增强生成",
            rewritten_query="检索增强生成",
            needs_rewrite=False,
            reason="查询已足够清晰",
        )

        assert result.original_query == result.rewritten_query
        assert result.needs_rewrite is False


class TestRewritePortProtocol:
    """RewritePort Protocol 签名与结构性子类型测试。"""

    def test_rewrite_port_is_protocol(self) -> None:
        """RewritePort 应是 typing.Protocol 的子类。"""
        assert issubclass(RewritePort, Protocol)

    def test_rewrite_method_signature(self) -> None:
        """rewrite 方法签名：keyword-only 参数，返回 RewriteResult。"""
        import inspect

        sig = inspect.signature(RewritePort.rewrite)

        params = list(sig.parameters.values())
        param_names = [p.name for p in params]

        # self + 2 keyword-only 参数
        assert param_names == [
            "self",
            "query",
            "kb_ids",
        ], f"参数名不匹配: {param_names}"

        for p in params[1:]:  # 跳过 self
            assert (
                p.kind == inspect.Parameter.KEYWORD_ONLY
            ), f"{p.name} 应为 KEYWORD_ONLY，实际: {p.kind}"

        # 验证返回类型注解为 RewriteResult
        assert (
            sig.return_annotation == RewriteResult
        ), f"返回类型应为 RewriteResult，实际: {sig.return_annotation}"

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
            """最小实现 — 原样返回查询，不做改写。"""

            async def rewrite(
                self,
                *,
                query: str,
                kb_ids: list[str],
            ) -> RewriteResult:
                return RewriteResult(
                    original_query=query,
                    rewritten_query=query,
                    needs_rewrite=False,
                    reason="no rewrite needed",
                )

            async def clear_cache(self, kb_id: str) -> None:
                pass

        instance = _MinimalRewriter()

        async def _run_rewrite() -> RewriteResult:
            return await instance.rewrite(
                query="什么是 RAG",
                kb_ids=["kb1", "kb2"],
            )

        result = asyncio.run(_run_rewrite())

        assert result.original_query == "什么是 RAG"
        assert result.rewritten_query == "什么是 RAG"
        assert result.needs_rewrite is False
        assert result.reason == "no rewrite needed"

        # 验证 clear_cache 也可正常调用
        async def _run_clear() -> None:
            await instance.clear_cache(kb_id="kb1")

        asyncio.run(_run_clear())  # 不应抛异常
