"""NoopRewriteProvider 单元测试。

TDD: RED → GREEN。验证直通查询改写提供者的行为正确性。
"""

from __future__ import annotations

import asyncio

from ragnexus.domain.ports import RewritePort, RewriteResult


class TestNoopRewriteProvider:
    """NoopRewriteProvider 直通行为测试。"""

    def test_provider_exists(self) -> None:
        """NoopRewriteProvider 应从 adapters.rewrite 包导入。"""
        from ragnexus.adapters.rewrite.noop import NoopRewriteProvider

        assert NoopRewriteProvider is not None

    def test_satisfies_rewrite_port_protocol(self) -> None:
        """NoopRewriteProvider 满足 RewritePort 协议 — 行为验证。

        验证方法存在、签名匹配、以及实际调用返回类型正确。
        """
        import inspect

        from ragnexus.adapters.rewrite.noop import NoopRewriteProvider

        instance = NoopRewriteProvider()
        cls = NoopRewriteProvider

        # 验证方法存在
        assert hasattr(cls, "rewrite"), "缺少 rewrite 方法"
        assert hasattr(cls, "clear_cache"), "缺少 clear_cache 方法"

        # 验证 rewrite 签名：self + keyword-only 参数
        rewrite_sig = inspect.signature(cls.rewrite)
        rewrite_params = list(rewrite_sig.parameters.values())
        assert (
            rewrite_sig.return_annotation == RewriteResult
        ), f"rewrite 返回类型应为 RewriteResult，实际: {rewrite_sig.return_annotation}"
        for p in rewrite_params[1:]:
            assert (
                p.kind == inspect.Parameter.KEYWORD_ONLY
            ), f"rewrite 参数 {p.name} 应为 KEYWORD_ONLY"

        # 验证 clear_cache 签名
        cc_sig = inspect.signature(cls.clear_cache)
        cc_params = list(cc_sig.parameters.values())
        assert len(cc_params) == 2  # self + kb_id
        assert cc_params[1].name == "kb_id"
        assert cc_params[1].annotation is str
        assert cc_sig.return_annotation is None

        # 验证实际行为：rewrite 返回 RewriteResult
        async def _run() -> RewriteResult:
            return await instance.rewrite(
                query="test query",
                kb_ids=["kb-1"],
            )

        result = asyncio.run(_run())
        assert isinstance(result, RewriteResult)

    def test_rewrite_returns_identity_no_modification(self) -> None:
        """rewrite() 直通：original_query == rewritten_query == 输入 query。"""
        from ragnexus.adapters.rewrite.noop import NoopRewriteProvider

        provider = NoopRewriteProvider()

        async def _run() -> RewriteResult:
            return await provider.rewrite(
                query="什么是向量数据库？",
                kb_ids=["kb-1", "kb-2"],
            )

        result = asyncio.run(_run())

        assert isinstance(result, RewriteResult)
        assert result.original_query == "什么是向量数据库？"
        assert result.rewritten_query == "什么是向量数据库？"
        assert result.original_query == result.rewritten_query
        assert result.needs_rewrite is False, "直通实现应设置 needs_rewrite=False"
        assert result.reason == "禁用改写，直通"

    def test_rewrite_custom_query_identity(self) -> None:
        """不同 query 的直通身份保持。"""
        from ragnexus.adapters.rewrite.noop import NoopRewriteProvider

        provider = NoopRewriteProvider()

        async def _run() -> RewriteResult:
            return await provider.rewrite(
                query="RAG 系统的核心组件有哪些？",
                kb_ids=[],
            )

        result = asyncio.run(_run())
        assert result.original_query == "RAG 系统的核心组件有哪些？"
        assert result.rewritten_query == "RAG 系统的核心组件有哪些？"
        assert result.needs_rewrite is False

    def test_clear_cache_is_noop(self) -> None:
        """clear_cache() 应为空实现，不抛异常。"""
        from ragnexus.adapters.rewrite.noop import NoopRewriteProvider

        provider = NoopRewriteProvider()

        async def _run() -> None:
            await provider.clear_cache("kb-1")
            await provider.clear_cache("nonexistent-kb")

        asyncio.run(_run())  # 通过即表示空实现正确
