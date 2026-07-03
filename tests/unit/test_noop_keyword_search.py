"""NoopKeywordSearchProvider 单元测试。

TDD: RED → GREEN。验证空关键词检索提供者的行为正确性。
"""

from __future__ import annotations

import asyncio

from ragnexus.domain.models import Chunk, SearchHit


def _make_chunk(i: int = 0, kb_id: str = "kb-test") -> Chunk:
    """创建默认测试用 Chunk 对象。"""
    return Chunk(
        id=f"doc-{i}:0",
        kb_id=kb_id,
        doc_id=f"doc-{i}",
        text=f"测试文本 {i}",
        vector=[0.1] * 1536,
        metadata={"source": f"test-{i}"},
    )


class TestNoopKeywordSearchProvider:
    """NoopKeywordSearchProvider 空实现行为测试。"""

    def test_provider_exists(self) -> None:
        """NoopKeywordSearchProvider 应从 adapters.keyword_search.noop 导入。"""
        from ragnexus.adapters.keyword_search.noop import NoopKeywordSearchProvider

        assert NoopKeywordSearchProvider is not None

    def test_satisfies_keyword_search_port_protocol(self) -> None:
        """NoopKeywordSearchProvider 满足 KeywordSearchPort 协议 — 行为验证。

        验证所有必需方法存在（upsert, search_by_keyword, delete），
        签名和返回类型正确，并验证实际行为正确性。
        """
        import inspect

        from ragnexus.adapters.keyword_search.noop import NoopKeywordSearchProvider

        instance = NoopKeywordSearchProvider()
        cls = NoopKeywordSearchProvider

        # 验证方法存在
        assert hasattr(cls, "search_by_keyword"), "缺少 search_by_keyword 方法"
        assert hasattr(cls, "upsert"), "缺少 upsert 方法"
        assert hasattr(cls, "delete"), "缺少 delete 方法"

        # 验证 search_by_keyword 签名
        sk_sig = inspect.signature(cls.search_by_keyword)
        sk_params = list(sk_sig.parameters.values())
        assert (
            len(sk_params) == 4
        ), f"search_by_keyword 应有 4 参数(self+kb_id+query+top_k)，实际: {len(sk_params)}"
        assert sk_params[1].name == "kb_id"
        assert sk_params[1].annotation is str
        assert sk_params[2].name == "query"
        assert sk_params[2].annotation is str
        assert sk_params[3].name == "top_k"
        assert sk_params[3].annotation is int
        assert (
            sk_sig.return_annotation == list[SearchHit]
        ), f"search_by_keyword 返回类型应为 list[SearchHit]，实际: {sk_sig.return_annotation}"

        # 验证 upsert 签名
        up_sig = inspect.signature(cls.upsert)
        up_params = list(up_sig.parameters.values())
        assert (
            len(up_params) == 3
        ), f"upsert 应有 3 参数(self+kb_id+chunks)，实际: {len(up_params)}"
        assert up_params[1].name == "kb_id"
        assert up_params[1].annotation is str
        assert up_params[2].name == "chunks"
        assert up_params[2].annotation == list[Chunk]
        assert up_sig.return_annotation is None

        # 验证 delete 签名
        del_sig = inspect.signature(cls.delete)
        del_params = list(del_sig.parameters.values())
        assert (
            len(del_params) == 3
        ), f"delete 应有 3 参数(self+kb_id+chunk_ids)，实际: {len(del_params)}"
        assert del_params[1].name == "kb_id"
        assert del_params[1].annotation is str
        assert del_params[2].name == "chunk_ids"
        assert del_params[2].annotation == list[str]
        assert del_sig.return_annotation is None

        # 验证实际行为：search_by_keyword 返回空 list
        async def _run_search() -> list[SearchHit]:
            return await instance.search_by_keyword(
                kb_id="kb-test",
                query="测试查询",
                top_k=10,
            )

        result = asyncio.run(_run_search())
        assert isinstance(result, list)
        assert len(result) == 0

    def test_search_by_keyword_returns_empty(self) -> None:
        """search_by_keyword() 始终返回空列表 []。"""
        from ragnexus.adapters.keyword_search.noop import NoopKeywordSearchProvider

        instance = NoopKeywordSearchProvider()

        async def _run() -> list[SearchHit]:
            return await instance.search_by_keyword(
                kb_id="kb-test",
                query="任意查询",
                top_k=5,
            )

        result = asyncio.run(_run())
        assert result == [], f"应返回空列表，实际: {result}"

    def test_search_by_keyword_empty_for_different_params(self) -> None:
        """不同的 kb_id、query、top_k 组合都应返回空列表。"""
        from ragnexus.adapters.keyword_search.noop import NoopKeywordSearchProvider

        instance = NoopKeywordSearchProvider()

        async def _run(kb_id: str, query: str, top_k: int) -> list[SearchHit]:
            return await instance.search_by_keyword(
                kb_id=kb_id,
                query=query,
                top_k=top_k,
            )

        # 多组参数验证，确保空实现不受输入影响
        cases = [
            ("kb-a", "hello", 3),
            ("kb-b", "world", 10),
            ("kb-c", "", 1),
        ]
        for kb_id, query, top_k in cases:
            result = asyncio.run(_run(kb_id, query, top_k))
            assert (
                result == []
            ), f"({kb_id}, {query}, {top_k}) 应返回 []，实际: {result}"

    def test_upsert_noop(self) -> None:
        """upsert() 应不抛异常，无副作用。"""
        from ragnexus.adapters.keyword_search.noop import NoopKeywordSearchProvider

        instance = NoopKeywordSearchProvider()
        chunks = [_make_chunk(i) for i in range(3)]

        async def _run() -> None:
            await instance.upsert(kb_id="kb-test", chunks=chunks)

        asyncio.run(_run())  # 不抛异常即通过

    def test_upsert_empty_chunks_noop(self) -> None:
        """upsert() 传入空 chunks 列表应不抛异常。"""
        from ragnexus.adapters.keyword_search.noop import NoopKeywordSearchProvider

        instance = NoopKeywordSearchProvider()

        async def _run() -> None:
            await instance.upsert(kb_id="kb-test", chunks=[])

        asyncio.run(_run())  # 不抛异常即通过

    def test_delete_noop(self) -> None:
        """delete() 应不抛异常，无副作用。"""
        from ragnexus.adapters.keyword_search.noop import NoopKeywordSearchProvider

        instance = NoopKeywordSearchProvider()

        async def _run() -> None:
            await instance.delete(kb_id="kb-test", chunk_ids=["chunk-0", "chunk-1"])

        asyncio.run(_run())  # 不抛异常即通过

    def test_delete_empty_ids_noop(self) -> None:
        """delete() 传入空 chunk_ids 列表应不抛异常。"""
        from ragnexus.adapters.keyword_search.noop import NoopKeywordSearchProvider

        instance = NoopKeywordSearchProvider()

        async def _run() -> None:
            await instance.delete(kb_id="kb-test", chunk_ids=[])

        asyncio.run(_run())  # 不抛异常即通过
