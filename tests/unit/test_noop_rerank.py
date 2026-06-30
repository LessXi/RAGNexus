"""NoopRerankProvider 单元测试。

TDD: RED → GREEN。验证直通重排提供者的行为正确性。
"""

from __future__ import annotations

import asyncio

from ragnexus.domain.models import SearchHit


class TestNoopRerankProvider:
    """NoopRerankProvider 直通行为测试。"""

    def test_provider_exists(self) -> None:
        """NoopRerankProvider 应从 adapters.rerank 包导入。"""
        from ragnexus.adapters.rerank.noop import NoopRerankProvider

        assert NoopRerankProvider is not None

    def test_satisfies_rerank_port_protocol(self) -> None:
        """NoopRerankProvider 满足 RerankPort 协议 — 行为验证。

        运行时通过 inspect 验证方法签名匹配 Protocol 定义，
        并实际调用验证返回类型正确。不使用 issubclass
        （RerankPort 非 @runtime_checkable）。
        """
        import inspect

        from ragnexus.adapters.rerank.noop import NoopRerankProvider

        instance = NoopRerankProvider()
        cls = NoopRerankProvider

        # 验证方法存在
        assert hasattr(cls, "rerank"), "缺少 rerank 方法"
        assert hasattr(cls, "clear_cache"), "缺少 clear_cache 方法"

        # 验证 rerank 签名：keyword-only 参数
        rerank_sig = inspect.signature(cls.rerank)
        rerank_params = list(rerank_sig.parameters.values())
        # self + 5 keyword-only 参数
        assert (
            rerank_sig.return_annotation == list[SearchHit]
        ), f"rerank 返回类型应为 list[SearchHit]，实际: {rerank_sig.return_annotation}"
        for p in rerank_params[1:]:
            assert (
                p.kind == inspect.Parameter.KEYWORD_ONLY
            ), f"rerank 参数 {p.name} 应为 KEYWORD_ONLY"

        # 验证 clear_cache 签名
        cc_sig = inspect.signature(cls.clear_cache)
        cc_params = list(cc_sig.parameters.values())
        assert len(cc_params) == 2  # self + kb_id
        assert cc_params[1].name == "kb_id"
        assert cc_params[1].annotation is str
        assert cc_sig.return_annotation is None

        # 验证实际行为：rerank 返回 list[SearchHit]
        async def _run() -> list[SearchHit]:
            return await instance.rerank(
                query="test",
                query_vector=[0.1],
                kb_ids=["kb1"],
                chunks=[],
                top_n=5,
            )

        result = asyncio.run(_run())
        assert isinstance(result, list)

    def test_rerank_returns_same_chunks_no_modification(self) -> None:
        """rerank() 直接返回原始 chunks，不排序，按 top_n 截断。

        禁用重排时的直通行为：保持顺序不变，裁剪到 top_n。"""
        from ragnexus.adapters.rerank.noop import NoopRerankProvider

        provider = NoopRerankProvider()

        chunks = [
            SearchHit(
                chunk_id="c1",
                kb_id="kb_alpha",
                doc_id="doc_a",
                score=0.5,
                text="中等相关",
                metadata={"page": 1},
            ),
            SearchHit(
                chunk_id="c3",
                kb_id="kb_alpha",
                doc_id="doc_a",
                score=0.9,
                text="高度相关",
                metadata={"page": 3},
            ),
            SearchHit(
                chunk_id="c2",
                kb_id="kb_alpha",
                doc_id="doc_a",
                score=0.3,
                text="低相关",
                metadata={"page": 2},
            ),
        ]

        async def _run() -> list[SearchHit]:
            return await provider.rerank(
                query="测试查询",
                query_vector=[0.1, 0.2, 0.3],
                kb_ids=["kb_alpha"],
                chunks=chunks,
                top_n=2,
            )

        result = asyncio.run(_run())

        # 返回的列表长度为 top_n（截断到 top_n）
        assert len(result) == 2, f"应截断到 top_n=2，期望 2，实际 {len(result)}"

        # 截断后创建新列表对象
        assert result is not chunks, "截断应创建新列表"

        # 分值不变 — 不排序，保持原始顺序（裁剪到 top_n）
        assert result[0].score == 0.5, "第一个元素分值不应改变"
        assert result[1].score == 0.9, "第二个元素分值不应改变"

        # 所有字段保持不变
        assert result[0].chunk_id == "c1"
        assert result[0].text == "中等相关"
        assert result[0].metadata == {"page": 1}
        assert result[1].chunk_id == "c3"
        assert result[1].text == "高度相关"
        assert result[1].metadata == {"page": 3}

    def test_rerank_empty_list_returns_empty(self) -> None:
        """空列表传入时应返回空列表。"""
        from ragnexus.adapters.rerank.noop import NoopRerankProvider

        provider = NoopRerankProvider()

        async def _run() -> list[SearchHit]:
            return await provider.rerank(
                query="测试",
                query_vector=[0.0],
                kb_ids=[],
                chunks=[],
                top_n=10,
            )

        result = asyncio.run(_run())
        assert result == []

    def test_rerank_truncates_to_top_n(self) -> None:
        """top_n < len(chunks) 时应截断到 top_n，防止返回超量 chunks。"""
        from ragnexus.adapters.rerank.noop import NoopRerankProvider

        provider = NoopRerankProvider()

        chunks = [
            SearchHit(
                chunk_id=f"c{i}",
                kb_id="kb1",
                doc_id="d1",
                score=float(i),
                text=f"chunk {i}",
                metadata={},
            )
            for i in range(5)
        ]

        async def _run() -> list[SearchHit]:
            return await provider.rerank(
                query="q",
                query_vector=[0.0],
                kb_ids=["kb1"],
                chunks=chunks,
                top_n=2,  # 请求只取前2，会截断
            )

        result = asyncio.run(_run())
        assert len(result) == 2, f"应截断到 top_n=2，期望 2，实际 {len(result)}"

    def test_clear_cache_is_noop(self) -> None:
        """clear_cache() 应为空实现，不抛异常。"""
        from ragnexus.adapters.rerank.noop import NoopRerankProvider

        provider = NoopRerankProvider()

        # 不应抛出任何异常
        async def _run() -> None:
            await provider.clear_cache("kb_any")

        asyncio.run(_run())  # 通过即表示空实现正确
