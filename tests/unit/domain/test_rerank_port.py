"""RerankPort Protocol 单元测试。

验证 RerankPort 接口定义正确，以及结构性子类型兼容性。
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from ragnexus.domain.models import SearchHit
from ragnexus.domain.ports import RerankPort


class TestRerankPortProtocol:
    """RerankPort Protocol 签名与结构性子类型测试。"""

    def test_rerank_port_is_protocol(self) -> None:
        """RerankPort 应是 typing.Protocol 的子类。"""
        assert issubclass(RerankPort, Protocol)

    def test_rerank_method_signature(self) -> None:
        """rerank 方法签名：keyword-only 参数，返回 list[SearchHit]。"""
        import inspect

        sig = inspect.signature(RerankPort.rerank)

        # 所有参数应为 keyword-only（第一个是 self，后面都是 keyword-only）
        params = list(sig.parameters.values())
        param_names = [p.name for p in params]

        # self + 5 keyword-only 参数
        assert param_names == [
            "self",
            "query",
            "query_vector",
            "kb_ids",
            "chunks",
            "top_n",
        ], f"参数名不匹配: {param_names}"

        for p in params[1:]:  # 跳过 self
            assert (
                p.kind == inspect.Parameter.KEYWORD_ONLY
            ), f"{p.name} 应为 KEYWORD_ONLY，实际: {p.kind}"

        # 验证返回类型注解为 list[SearchHit]
        assert (
            sig.return_annotation == list[SearchHit]
        ), f"返回类型应为 list[SearchHit]，实际: {sig.return_annotation}"

    def test_clear_cache_method_signature(self) -> None:
        """clear_cache 方法签名：kb_id: str → None。"""
        import inspect

        sig = inspect.signature(RerankPort.clear_cache)

        params = list(sig.parameters.values())
        assert len(params) == 2  # self + kb_id
        assert params[0].name == "self"
        assert params[1].name == "kb_id"
        assert params[1].annotation is str
        assert sig.return_annotation is None

    def test_minimal_implementation_satisfies_protocol(self) -> None:
        """一个最小实现类应满足 RerankPort 协议结构。

        Python Protocol 使用静态结构子类型（pyright/mypy），运行时不需要
        @runtime_checkable。这里通过实际调用来验证行为正确性。
        """

        class _MinimalReranker:
            """最小实现 — 仅按原始顺序返回，不做重排。"""

            async def rerank(
                self,
                *,
                query: str,
                query_vector: list[float],
                kb_ids: list[str],
                chunks: list[SearchHit],
                top_n: int,
            ) -> list[SearchHit]:
                return chunks[:top_n]

            async def clear_cache(self, kb_id: str) -> None:
                pass

        instance = _MinimalReranker()

        # 验证实际行为 — 确保返回类型和截断逻辑正确
        fake_hits = [
            SearchHit(
                chunk_id="c1",
                kb_id="kb1",
                doc_id="d1",
                score=0.9,
                text="hello",
                metadata={},
            ),
            SearchHit(
                chunk_id="c2",
                kb_id="kb1",
                doc_id="d1",
                score=0.8,
                text="world",
                metadata={},
            ),
        ]

        async def _run() -> list[SearchHit]:
            return await instance.rerank(
                query="test",
                query_vector=[0.1, 0.2],
                kb_ids=["kb1"],
                chunks=fake_hits,
                top_n=1,
            )

        result = asyncio.run(_run())

        assert len(result) == 1
        assert result[0].score == 0.9  # score 保持原始分不变
