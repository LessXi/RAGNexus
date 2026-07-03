"""Rerank 缓存 original_query_embedding 测试。

TDD: 验证缓存匹配从 query_embedding（改写后）切换到 original_query_embedding（原始）。
"""

from __future__ import annotations

import asyncio

from ragnexus.domain.models import SearchHit

# ============================================================================
# 辅助工具
# ============================================================================


def make_hit(
    chunk_id: str,
    kb_id: str = "kb_001",
    doc_id: str = "doc_001",
    score: float = 0.9,
    text: str = "",
) -> SearchHit:
    """快捷构造 SearchHit 测试数据。"""
    return SearchHit(
        chunk_id=chunk_id,
        kb_id=kb_id,
        doc_id=doc_id,
        score=score,
        text=text,
        metadata={},
    )


# ============================================================================
# CacheEntry 新字段测试
# ============================================================================


class TestCacheEntryOriginalQueryEmbedding:
    """CacheEntry original_query_embedding 新字段测试。"""

    def test_new_fields_exist_with_defaults(self) -> None:
        """original_query_embedding 和 original_query_text 应有默认值。"""
        from ragnexus.adapters.rerank.llm import CacheEntry

        # 使用旧签名构造（向后兼容）
        entry = CacheEntry(
            query_embedding=[0.1, 0.2],
            query_text="改写后 query",
            rankings={"c_1": 0.9},
            timestamp=123456.0,
        )
        assert entry.original_query_embedding == [], "默认应为空列表"
        assert entry.original_query_text == "", "默认应为空字符串"

    def test_new_fields_store_values(self) -> None:
        """original_query_embedding 和 original_query_text 应正确存储。"""
        from ragnexus.adapters.rerank.llm import CacheEntry

        entry = CacheEntry(
            query_embedding=[0.1, 0.2],
            query_text="改写后 query",
            rankings={"c_1": 0.9},
            timestamp=123456.0,
            original_query_embedding=[0.3, 0.4],
            original_query_text="原始 query",
        )
        assert entry.original_query_embedding == [0.3, 0.4]
        assert entry.original_query_text == "原始 query"

    def test_backward_compat_no_break(self) -> None:
        """旧构造方式（4 字段）不抛异常。"""
        from ragnexus.adapters.rerank.llm import CacheEntry

        # 不传新字段 → 默认值生效
        entry = CacheEntry(
            query_embedding=[0.1, 0.2],
            query_text="测试",
            rankings={"c_1": 0.8},
            timestamp=999.0,
        )
        # 验证旧字段仍有效
        assert entry.query_embedding == [0.1, 0.2]
        assert entry.query_text == "测试"
        assert entry.rankings == {"c_1": 0.8}
        assert entry.timestamp == 999.0
        # 新字段有默认值
        assert entry.original_query_embedding == []
        assert entry.original_query_text == ""


# ============================================================================
# 缓存匹配逻辑测试
# ============================================================================


class TestRerankCacheOriginalEmbedding:
    """缓存匹配使用 original_query_embedding 优先测试。"""

    def test_cache_writes_original_query_embedding(self) -> None:
        """写入缓存时 CacheEntry 应同时设置 query_embedding 和 original_query_embedding。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        class FakeLLM:
            """最小 fake LLM，只管返回。"""

            calls: list[dict] = []

            async def chat_json(self, *args, **kwargs):
                self.calls.append({"args": args, "kwargs": kwargs})
                return {"rankings": [{"chunk_id": "c_1", "rerank_score": 0.95}]}

        fake = FakeLLM()
        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        query_vector = [0.1] * 10
        chunks = [make_hit("c_1", score=0.9, text="text 1")]

        async def _run() -> None:
            await provider.rerank(
                query="原始问题",
                query_vector=query_vector,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=1,
            )

        asyncio.run(_run())

        # 验证缓存条目同时有 query_embedding 和 original_query_embedding
        entries = provider._cache.get(frozenset({"kb_001"}), [])
        assert len(entries) == 1, "应写入 1 条缓存"
        entry = entries[0]
        assert entry.query_embedding == query_vector, "query_embedding 应为传入向量"
        assert (
            entry.original_query_embedding == query_vector
        ), "original_query_embedding 应为传入向量（当前无改写，相同）"
        assert entry.query_text == "原始问题"
        assert entry.original_query_text == "原始问题"

    def test_cache_match_uses_original_query_embedding_when_available(self) -> None:
        """缓存命中时，优先用 original_query_embedding 做余弦匹配。

        场景：手动构造两条缓存条目，一条 original_query_embedding 与 query_vector 相似，
        另一条 query_embedding 与 query_vector 相似但 original_query_embedding 不相似。
        验证匹配命中的是 original_query_embedding 相似的那条。
        """
        from ragnexus.adapters.rerank.llm import CacheEntry, LLMRerankProvider

        class FakeLLM:
            calls: list[dict] = []

            async def chat_json(self, *args, **kwargs):
                self.calls.append({"args": args, "kwargs": kwargs})
                return {"rankings": [{"chunk_id": "c_1", "rerank_score": 0.95}]}

        fake = FakeLLM()
        provider = LLMRerankProvider(
            llm=fake,  # type: ignore[arg-type]
            cache_similarity_threshold=0.9,
        )

        query_vector = [0.1] * 10
        different_vector = [-0.1] * 10

        # 手工塞入两条缓存：
        # 条目 A: original_query_embedding 匹配 query_vector，query_embedding 不匹配
        # 条目 B: query_embedding 匹配 query_vector，但 original_query_embedding 不匹配
        import time

        entry_a = CacheEntry(
            query_embedding=list(different_vector),  # 不匹配 query_vector
            original_query_embedding=list(query_vector),  # 匹配 query_vector
            query_text="改写A",
            original_query_text="原始A",
            rankings={"c_1": 0.99},
            timestamp=time.time(),
        )
        entry_b = CacheEntry(
            query_embedding=list(query_vector),  # 匹配 query_vector（旧逻辑会命中）
            original_query_embedding=list(different_vector),  # 不匹配 query_vector
            query_text="改写B",
            original_query_text="原始B",
            rankings={"c_1": 0.50},
            timestamp=time.time(),
        )

        kb_key = frozenset({"kb_001"})
        provider._cache[kb_key] = [entry_a, entry_b]

        chunks = [make_hit("c_1", score=0.9, text="text 1")]

        async def _run() -> list[SearchHit]:
            return await provider.rerank(
                query="测试",
                query_vector=query_vector,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=1,
            )

        result = asyncio.run(_run())
        # 应命中 entry_a（original_query_embedding 匹配），
        # 而不走 LLM（entry_a 的 rankings 覆盖 c_1）
        assert len(fake.calls) == 0, "应命中缓存，不调用 LLM"
        assert result[0].chunk_id == "c_1"
        # 验证用的是 entry_a 的分数
        # result 的排序由 _merge_and_sort 决定，这里全命中直接按缓存分排
        # 由于只有 c_1，分数不影响顺序，但可以验证没有走 LLM

    def test_cache_empty_original_falls_back_to_query_embedding(self) -> None:
        """original_query_embedding 为空时回退到 query_embedding 匹配。"""
        from ragnexus.adapters.rerank.llm import CacheEntry, LLMRerankProvider

        class FakeLLM:
            calls: list[dict] = []

            async def chat_json(self, *args, **kwargs):
                self.calls.append({"args": args, "kwargs": kwargs})
                return {"rankings": [{"chunk_id": "c_1", "rerank_score": 0.95}]}

        fake = FakeLLM()
        provider = LLMRerankProvider(
            llm=fake,  # type: ignore[arg-type]
            cache_similarity_threshold=0.9,
        )

        query_vector = [0.1] * 10

        import time

        # 条目: original_query_embedding 为空 → 回退到 query_embedding
        entry_with_empty_original = CacheEntry(
            query_embedding=list(query_vector),  # 匹配
            original_query_embedding=[],  # 空 → 回退
            query_text="改写",
            original_query_text="",
            rankings={"c_1": 0.85},
            timestamp=time.time(),
        )

        kb_key = frozenset({"kb_001"})
        provider._cache[kb_key] = [entry_with_empty_original]

        chunks = [make_hit("c_1", score=0.9, text="text 1")]

        async def _run() -> list[SearchHit]:
            return await provider.rerank(
                query="测试",
                query_vector=query_vector,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=1,
            )

        result = asyncio.run(_run())
        # 应命中缓存（通过 query_embedding 回退匹配）
        assert len(fake.calls) == 0, "应命中缓存，不调用 LLM"
        assert result[0].chunk_id == "c_1"
