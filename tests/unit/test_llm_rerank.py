"""LLMRerankProvider 单元测试。

TDD: RED → GREEN。覆盖缓存、LLM 调用、JSON 防御、降级、日志等完整流程。
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

from ragnexus.domain.models import SearchHit

# ============================================================================
# FakeLLMProvider — 用于测试的可控 LLM 实现
# ============================================================================


class FakeLLMProvider:
    """测试用 LLMProvider，允许预设 chat_json 返回值。

    不继承 ABC，因为测试不需要严格类型检查。
    通过 responses 队列控制 LLM 返回，队列空了返回默认空 dict。
    """

    def __init__(self, responses: list[dict] | None = None):
        self.responses: list[dict] = list(responses or [])
        self.calls: list[dict] = []  # 记录每次调用的参数

    async def chat_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict,
        temperature: float = 0.0,
        timeout_seconds: int | None = None,
    ) -> dict:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_payload": user_payload,
                "temperature": temperature,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return {}


# ============================================================================
# 辅助工具
# ============================================================================


def make_hit(
    chunk_id: str,
    kb_id: str = "kb_001",
    doc_id: str = "doc_001",
    score: float = 0.9,
    text: str = "",
    metadata: dict[str, Any] | None = None,
) -> SearchHit:
    """快捷构造 SearchHit 测试数据。"""
    return SearchHit(
        chunk_id=chunk_id,
        kb_id=kb_id,
        doc_id=doc_id,
        score=score,
        text=text,
        metadata=metadata or {},
    )


def cosine_sim(a: list[float], b: list[float]) -> float:
    """计算两个向量的 cosine 相似度（纯测试辅助）。"""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ============================================================================
# 测试类
# ============================================================================


class TestLLMRerankProviderConstruction:
    """构造器参数存储测试。"""

    def test_default_construction(self):
        """默认构造器参数应正确存储。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider()
        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        assert provider.llm is fake
        assert provider.max_candidates == 20
        assert provider.chunk_max_chars == 1000
        assert provider.cache_similarity_threshold == 0.95
        assert provider.cache_max_entries == 100
        assert provider.cache_ttl_seconds == 300
        assert provider.cache_preview_max_chars == 150
        assert provider.temperature == 0.0
        assert isinstance(provider._cache, dict)

    def test_custom_construction(self):
        """自定义构造器参数应正确存储。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider()
        provider = LLMRerankProvider(
            llm=fake,  # type: ignore[arg-type]
            max_candidates=10,
            chunk_max_chars=500,
            cache_similarity_threshold=0.90,
            cache_max_entries=50,
            cache_ttl_seconds=600,
            cache_preview_max_chars=100,
            temperature=0.3,
        )
        assert provider.max_candidates == 10
        assert provider.chunk_max_chars == 500
        assert provider.cache_similarity_threshold == 0.90
        assert provider.cache_max_entries == 50
        assert provider.cache_ttl_seconds == 600
        assert provider.cache_preview_max_chars == 100
        assert provider.temperature == 0.3


class TestLLMRerankProviderRerank:
    """rerank 正常流程测试。"""

    def test_rerank_calls_llm_and_returns_reordered(self):
        """rerank 应调用 LLM、解析 rankings、按 rerank_score 排序返回。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider(
            responses=[
                {
                    "rankings": [
                        {"chunk_id": "c_2", "rerank_score": 0.95, "reason": "best"},
                        {"chunk_id": "c_1", "rerank_score": 0.30, "reason": "ok"},
                        {"chunk_id": "c_3", "rerank_score": 0.80, "reason": "good"},
                    ]
                }
            ]
        )

        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        chunks = [
            make_hit("c_1", score=0.91, text="text 1"),
            make_hit("c_2", score=0.85, text="text 2"),
            make_hit("c_3", score=0.70, text="text 3"),
        ]

        async def _run() -> list[SearchHit]:
            return await provider.rerank(
                query="测试问题",
                query_vector=[0.1] * 10,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=3,
            )

        result = asyncio.run(_run())

        # 按 rerank_score 降序：c_2(0.95), c_3(0.80), c_1(0.30)
        assert len(result) == 3
        assert result[0].chunk_id == "c_2"
        assert result[1].chunk_id == "c_3"
        assert result[2].chunk_id == "c_1"

        # LLM 应该被调用了 1 次
        assert len(fake.calls) == 1

    def test_rerank_preserves_original_score(self):
        """重排只改变顺序，不改变 score 字段（保持向量原始分）。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider(
            responses=[
                {
                    "rankings": [
                        {"chunk_id": "c_2", "rerank_score": 0.95},
                        {"chunk_id": "c_1", "rerank_score": 0.30},
                    ]
                }
            ]
        )

        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        chunks = [
            make_hit("c_1", score=0.91),
            make_hit("c_2", score=0.85),
        ]

        async def _run() -> list[SearchHit]:
            return await provider.rerank(
                query="测试",
                query_vector=[0.1] * 10,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=2,
            )

        result = asyncio.run(_run())

        # c_2 的 score 仍然是 0.85（不是 0.95）
        c2 = next(r for r in result if r.chunk_id == "c_2")
        assert c2.score == 0.85
        c1 = next(r for r in result if r.chunk_id == "c_1")
        assert c1.score == 0.91

    def test_rerank_truncates_to_top_n(self):
        """rerank 应裁回 top_n 条结果。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider(
            responses=[
                {
                    "rankings": [
                        {"chunk_id": f"c_{i}", "rerank_score": 0.9 - i * 0.1}
                        for i in range(10)
                    ]
                }
            ]
        )

        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        chunks = [make_hit(f"c_{i}", score=0.9 - i * 0.05) for i in range(10)]

        async def _run() -> list[SearchHit]:
            return await provider.rerank(
                query="测试",
                query_vector=[0.1] * 10,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=3,
            )

        result = asyncio.run(_run())
        assert len(result) == 3


class TestLLMRerankProviderCache:
    """缓存逻辑测试。"""

    def test_cache_full_hit_skips_llm(self):
        """全命中缓存时应跳过 LLM，直接按缓存分排序返回。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider()

        # 先调用一次写入缓存
        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
        fake.responses.append(
            {
                "rankings": [
                    {"chunk_id": "c_1", "rerank_score": 0.80},
                    {"chunk_id": "c_2", "rerank_score": 0.95},
                ]
            }
        )

        query_vector = [0.1] * 10
        chunks = [
            make_hit("c_1", score=0.91, text="text 1"),
            make_hit("c_2", score=0.85, text="text 2"),
        ]

        async def _first_run():
            return await provider.rerank(
                query="测试问题",
                query_vector=query_vector,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=2,
            )

        asyncio.run(_first_run())
        assert len(fake.calls) == 1  # 第一次调用 LLM

        # 第二次：相同 query_vector，应命中缓存
        result2 = asyncio.run(_first_run())
        assert len(fake.calls) == 1  # 未新增 LLM 调用
        # 结果按缓存分排序
        assert result2[0].chunk_id == "c_2"  # 0.95
        assert result2[1].chunk_id == "c_1"  # 0.80

    def test_cache_partial_hit_payload_includes_reference_scores(self):
        """部分命中时 LLM payload 应包含 reference_scores 标尺。

        场景: 第一次缓存 {c_1, c_2, c_3} 的 rankings，
        第二次用相同 query_vector 但 chunks 含 {c_1, c_2, c_4}。
        c_1, c_2 命中缓存 → reference_scores，c_4 送 LLM → candidates。
        """
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider()
        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        query_vector = [0.1] * 10

        # 第一次：3 个 chunks 全送 LLM，写入缓存
        chunks1 = [
            make_hit("c_1", score=0.91, text="text 1"),
            make_hit("c_2", score=0.85, text="text 2"),
            make_hit("c_3", score=0.70, text="text 3"),
        ]
        fake.responses.append(
            {
                "rankings": [
                    {"chunk_id": "c_1", "rerank_score": 0.80},
                    {"chunk_id": "c_2", "rerank_score": 0.95},
                    {"chunk_id": "c_3", "rerank_score": 0.60},
                ]
            }
        )
        asyncio.run(
            provider.rerank(
                query="测试问题",
                query_vector=query_vector,
                kb_ids=["kb_001"],
                chunks=chunks1,
                top_n=3,
            )
        )

        # 第二次：相同 query_vector（cosine=1.0，缓存命中）
        # chunks 含 c_4 不在缓存中 → 部分命中
        chunks2 = [
            make_hit("c_1", score=0.91, text="text 1"),
            make_hit("c_2", score=0.85, text="text 2"),
            make_hit("c_4", score=0.65, text="text 4"),  # 不在缓存中
        ]
        fake.responses.append({"rankings": [{"chunk_id": "c_4", "rerank_score": 0.75}]})

        asyncio.run(
            provider.rerank(
                query="测试问题",
                query_vector=query_vector,
                kb_ids=["kb_001"],
                chunks=chunks2,
                top_n=3,
            )
        )

        payload = fake.calls[1]["user_payload"]
        assert (
            "reference_scores" in payload
        ), "部分命中场景 payload 应包含 reference_scores"
        # candidates 应只包含未命中的 c_4
        candidate_ids = {c["chunk_id"] for c in payload["candidates"]}
        assert candidate_ids == {
            "c_4"
        }, f"candidates 应只含未命中 chunk，实际: {candidate_ids}"
        # reference_scores 应包含 c_1, c_2
        ref_ids = {r["chunk_id"] for r in payload["reference_scores"]}
        assert ref_ids == {
            "c_1",
            "c_2",
        }, f"reference_scores 应含命中 chunk，实际: {ref_ids}"

    def test_cache_similarity_mismatch_goes_to_llm(self):
        """缓存向量不相似时应走 LLM。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider()

        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        query_vector_a = [0.1] * 10
        chunks = [
            make_hit("c_1", score=0.9, text="text 1"),
        ]

        # 第一次写入缓存
        fake.responses.append(
            {
                "rankings": [{"chunk_id": "c_1", "rerank_score": 0.8}],
            }
        )
        asyncio.run(
            provider.rerank(
                query="问题A",
                query_vector=query_vector_a,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=1,
            )
        )

        # 第二次：非常不同的 query_vector
        fake.responses.append(
            {
                "rankings": [{"chunk_id": "c_1", "rerank_score": 0.7}],
            }
        )
        asyncio.run(
            provider.rerank(
                query="问题B",
                query_vector=[-0.1] * 10,  # 完全不同
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=1,
            )
        )

        # 两次都调了 LLM
        assert len(fake.calls) == 2

    def test_cache_tll_expiry(self):
        """TTL 过期缓存不应被命中。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider()
        provider = LLMRerankProvider(llm=fake, cache_ttl_seconds=300)  # type: ignore[arg-type]

        query_vector = [0.1] * 10
        chunks = [make_hit("c_1", score=0.9, text="text 1")]

        fake.responses.append(
            {
                "rankings": [{"chunk_id": "c_1", "rerank_score": 0.8}],
            }
        )
        asyncio.run(
            provider.rerank(
                query="测试",
                query_vector=query_vector,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=1,
            )
        )

        # 将缓存条目的 timestamp 改为很久以前（模拟 TTL 过期）
        import time

        for entry in provider._cache.get(frozenset({"kb_001"}), []):
            entry.timestamp = time.time() - 600  # 10 分钟前
        # 第二次调用：缓存应已过期，走 LLM
        fake.responses.append(
            {
                "rankings": [{"chunk_id": "c_1", "rerank_score": 0.7}],
            }
        )
        asyncio.run(
            provider.rerank(
                query="测试",
                query_vector=query_vector,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=1,
            )
        )

        assert len(fake.calls) == 2


class TestLLMRerankProviderCandidateTruncation:
    """候选截断相关测试。"""

    def test_truncates_to_max_candidates(self):
        """超过 max_candidates 时应截断。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider(
            responses=[
                {
                    "rankings": [
                        {"chunk_id": f"c_{i}", "rerank_score": 0.5} for i in range(3)
                    ]
                }
            ]
        )

        provider = LLMRerankProvider(llm=fake, max_candidates=3)  # type: ignore[arg-type]

        chunks = [make_hit(f"c_{i}", score=0.9 - i * 0.05) for i in range(10)]

        async def _run():
            return await provider.rerank(
                query="测试",
                query_vector=[0.1] * 10,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=3,
            )

        asyncio.run(_run())

        # LLM payload 中 candidates 不应超过 3
        payload = fake.calls[0]["user_payload"]
        assert len(payload["candidates"]) == 3

    def test_text_truncates_at_chunk_max_chars(self):
        """chunk 文本应截断到 chunk_max_chars。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider(
            responses=[{"rankings": [{"chunk_id": "c_1", "rerank_score": 0.8}]}]
        )

        provider = LLMRerankProvider(llm=fake, chunk_max_chars=50)  # type: ignore[arg-type]

        long_text = "A" * 200
        chunks = [make_hit("c_1", score=0.9, text=long_text)]

        async def _run():
            return await provider.rerank(
                query="测试",
                query_vector=[0.1] * 10,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=1,
            )

        asyncio.run(_run())

        payload = fake.calls[0]["user_payload"]
        assert len(payload["candidates"][0]["content"]) <= 50


class TestLLMRerankProviderJsonDefense:
    """JSON 解析防御测试。"""

    def test_parse_plain_json(self):
        """Layer 1: 普通 JSON 应正确解析。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider(
            responses=[{"rankings": [{"chunk_id": "c_1", "rerank_score": 0.9}]}]
        )

        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
        chunks = [make_hit("c_1", score=0.9, text="test")]

        async def _run():
            return await provider.rerank(
                query="测试",
                query_vector=[0.1] * 10,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=1,
            )

        result = asyncio.run(_run())
        assert len(result) == 1

    def test_parse_markdown_json_block(self):
        """Layer 2: LLM 返回 markdown 包裹的 JSON 应正确提取。"""

        # FakeLLMProvider 返回 dict 但实际 LLM 返回的可能是字符串
        # 我们需要模拟 chat_json 返回原始文本的场景
        # 这里验证的是解析逻辑，所以直接用内部解析方法
        from ragnexus.adapters.rerank.llm import _parse_rankings_json

        markdown_json = (
            '```json\n{"rankings": [{"chunk_id": "c_1", "rerank_score": 0.9}]}\n```'
        )
        result = _parse_rankings_json(markdown_json)
        assert len(result) == 1
        assert result[0]["chunk_id"] == "c_1"
        assert result[0]["rerank_score"] == 0.9

    def test_parse_json_in_text(self):
        """Layer 3: 文本中夹杂 JSON 应正确提取。"""
        from ragnexus.adapters.rerank.llm import _parse_rankings_json

        messy = '这是分析结果 {"rankings": [{"chunk_id": "c_1", "rerank_score": 0.9}]} 分析完毕'
        result = _parse_rankings_json(messy)
        assert len(result) == 1
        assert result[0]["chunk_id"] == "c_1"

    def test_parse_all_failed_returns_empty(self):
        """Layer 4: 全失败时应返回空列表。"""
        from ragnexus.adapters.rerank.llm import _parse_rankings_json

        result = _parse_rankings_json("not json at all")
        assert result == []


class TestLLMRerankProviderDegradation:
    """降级逻辑测试。"""

    def test_degrade_on_llm_exception(self):
        """LLM 抛异常时降级返回原始向量排序。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider(responses=[RuntimeError("LLM boom")])

        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        chunks = [
            make_hit("c_2", score=0.85, text="text 2"),
            make_hit("c_1", score=0.91, text="text 1"),
            make_hit("c_3", score=0.70, text="text 3"),
        ]

        async def _run():
            return await provider.rerank(
                query="测试",
                query_vector=[0.1] * 10,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=2,
            )

        result = asyncio.run(_run())

        # 降级：不抛异常，返回原始向量排序的前 top_n
        assert len(result) == 2
        # 原始向量排序：c_1(0.91), c_2(0.85), c_3(0.70)
        assert result[0].chunk_id == "c_1"
        assert result[1].chunk_id == "c_2"
        # score 不变
        assert result[0].score == 0.91
        assert result[1].score == 0.85

    def test_degrade_on_json_parse_failure(self):
        """JSON 解析全失败时降级返回原始排序。

        模拟 LLM 返回无法解析的 dict（无 rankings 字段）。
        """
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider(responses=[{"garbage": "no rankings"}])

        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        chunks = [
            make_hit("c_1", score=0.91, text="text 1"),
            make_hit("c_2", score=0.85, text="text 2"),
        ]

        async def _run():
            return await provider.rerank(
                query="测试",
                query_vector=[0.1] * 10,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=2,
            )

        result = asyncio.run(_run())

        # 降级返回原始排序
        assert len(result) == 2
        assert result[0].chunk_id == "c_1"

    def test_degrade_never_throws(self):
        """rerank 在任何情况下都不应抛异常。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        # 空 chunks
        fake = FakeLLMProvider()
        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        async def _run():
            return await provider.rerank(
                query="测试",
                query_vector=[0.1] * 10,
                kb_ids=["kb_001"],
                chunks=[],
                top_n=5,
            )

        result = asyncio.run(_run())
        assert result == []


class TestLLMRerankProviderClearCache:
    """clear_cache 测试。"""

    def test_clear_cache_removes_kb_entries(self):
        """clear_cache 应清空指定 KB 的缓存。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider(
            responses=[
                {"rankings": [{"chunk_id": "c_1", "rerank_score": 0.8}]},
                {"rankings": [{"chunk_id": "c_1", "rerank_score": 0.7}]},
            ]
        )

        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        query_vector = [0.1] * 10
        chunks = [make_hit("c_1", score=0.9, text="text 1")]

        # 第一次调用写入缓存
        asyncio.run(
            provider.rerank(
                query="测试",
                query_vector=query_vector,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=1,
            )
        )
        assert len(fake.calls) == 1

        # 清空缓存
        asyncio.run(provider.clear_cache("kb_001"))

        # 第二次应再次调用 LLM（缓存被清空）
        asyncio.run(
            provider.rerank(
                query="测试",
                query_vector=query_vector,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=1,
            )
        )
        assert len(fake.calls) == 2

    def test_clear_cache_nonexistent_kb(self):
        """clear_cache 对不存在的 KB 不应抛异常。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider()
        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        async def _run():
            await provider.clear_cache("nonexistent")

        asyncio.run(_run())  # 不应抛异常


class TestLLMRerankProviderPayloadConstruction:
    """LLM payload 构造测试。"""

    def test_payload_structure_full_miss(self):
        """全 miss 场景下 payload 应包含 query、candidates、top_n。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider(
            responses=[
                {
                    "rankings": [
                        {"chunk_id": "c_1", "rerank_score": 0.9},
                        {"chunk_id": "c_2", "rerank_score": 0.8},
                    ]
                }
            ]
        )

        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        chunks = [
            make_hit(
                "c_1",
                score=0.91,
                doc_id="d1",
                text="chunk one",
                metadata={"heading": "标题一"},
            ),
            make_hit("c_2", score=0.85, doc_id="d2", text="chunk two"),
        ]

        async def _run():
            return await provider.rerank(
                query="测试问题?",
                query_vector=[0.1] * 10,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=2,
            )

        asyncio.run(_run())

        payload = fake.calls[0]["user_payload"]
        assert payload["query"] == "测试问题?"
        assert payload["top_n"] == 2
        assert len(payload["candidates"]) == 2

        c1 = payload["candidates"][0]
        assert c1["chunk_id"] == "c_1"
        assert c1["document_id"] == "d1"
        assert c1["title"] == "标题一"
        assert c1["content"] == "chunk one"
        assert c1["vector_score"] == 0.91

        c2 = payload["candidates"][1]
        assert c2["title"] == ""  # 无 heading

    def test_payload_title_none_fallback(self):
        """metadata 无 heading 时 title 应为空字符串。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider(
            responses=[{"rankings": [{"chunk_id": "c_1", "rerank_score": 0.9}]}]
        )

        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        chunks = [make_hit("c_1", score=0.9, text="test", metadata={})]

        async def _run():
            return await provider.rerank(
                query="测试",
                query_vector=[0.1] * 10,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=1,
            )

        asyncio.run(_run())

        payload = fake.calls[0]["user_payload"]
        assert payload["candidates"][0]["title"] == ""


class TestLLMRerankProviderScoreEdgeCases:
    """分数边界测试。"""

    def test_llm_missing_chunk_id_gets_default_score(self):
        """LLM 未返回某个 chunk 时，该 chunk 默认 rerank_score = 0。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider(
            responses=[
                {
                    "rankings": [
                        {"chunk_id": "c_1", "rerank_score": 0.9},
                        # c_2 被 LLM 漏掉
                    ]
                }
            ]
        )

        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        chunks = [
            make_hit("c_1", score=0.91, text="t1"),
            make_hit("c_2", score=0.85, text="t2"),
        ]

        async def _run():
            return await provider.rerank(
                query="测试",
                query_vector=[0.1] * 10,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=2,
            )

        result = asyncio.run(_run())

        # c_1 (0.9) 在前，c_2 (0.0) 在后
        assert result[0].chunk_id == "c_1"
        assert result[1].chunk_id == "c_2"

    def test_llm_unknown_chunk_id_ignored(self):
        """LLM 返回不存在的 chunk_id 应被忽略。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider(
            responses=[
                {
                    "rankings": [
                        {"chunk_id": "c_1", "rerank_score": 0.9},
                        {
                            "chunk_id": "c_unknown",
                            "rerank_score": 0.99,
                        },  # 不在输入 chunks 中
                    ]
                }
            ]
        )

        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        chunks = [make_hit("c_1", score=0.91, text="t1")]

        async def _run():
            return await provider.rerank(
                query="测试",
                query_vector=[0.1] * 10,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=1,
            )

        result = asyncio.run(_run())
        assert len(result) == 1
        assert result[0].chunk_id == "c_1"

    def test_rerank_score_clamped_to_0_1(self):
        """超出 [0,1] 的 rerank_score 应被 clamp。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider(
            responses=[
                {
                    "rankings": [
                        {"chunk_id": "c_1", "rerank_score": 1.5},
                        {"chunk_id": "c_2", "rerank_score": -0.5},
                    ]
                }
            ]
        )

        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        chunks = [
            make_hit("c_1", score=0.91, text="t1"),
            make_hit("c_2", score=0.85, text="t2"),
        ]

        async def _run():
            return await provider.rerank(
                query="测试",
                query_vector=[0.1] * 10,
                kb_ids=["kb_001"],
                chunks=chunks,
                top_n=2,
            )

        result = asyncio.run(_run())
        assert len(result) == 2
        # c_1 的 rerank_score 被 clamp 到 1.0，应排前面
        assert result[0].chunk_id == "c_1"  # clamped to 1.0
        # score 仍然是原始向量分
        assert result[0].score == 0.91


class TestCacheEntry:
    """CacheEntry 数据类测试。"""

    def test_cache_entry_fields(self):
        """CacheEntry 应正确存储字段。"""
        from ragnexus.adapters.rerank.llm import CacheEntry

        entry = CacheEntry(
            query_embedding=[0.1, 0.2],
            query_text="测试",
            rankings={"c_1": 0.9},
            timestamp=123456.0,
        )
        assert entry.query_embedding == [0.1, 0.2]
        assert entry.query_text == "测试"
        assert entry.rankings == {"c_1": 0.9}
        assert entry.timestamp == 123456.0


class TestLLMRerankProviderFrozensetCacheIsolation:
    """frozenset 多 KB 缓存隔离测试。"""

    def test_frozenset_kb1_not_hit_kb2(self):
        """frozenset({"kb1"}) 缓存不命中 frozenset({"kb2"})。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider()
        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        query_vector = [0.1] * 10
        chunks = [make_hit("c_1", score=0.9, text="text 1")]

        fake.responses.append({"rankings": [{"chunk_id": "c_1", "rerank_score": 0.8}]})
        asyncio.run(
            provider.rerank(
                query="测试",
                query_vector=query_vector,
                kb_ids=["kb1"],
                chunks=chunks,
                top_n=1,
            )
        )
        assert len(fake.calls) == 1

        # 第二次：相同 query/vector，但 kb_ids=["kb2"] → frozenset 键不同
        fake.responses.append({"rankings": [{"chunk_id": "c_1", "rerank_score": 0.7}]})
        asyncio.run(
            provider.rerank(
                query="测试",
                query_vector=query_vector,
                kb_ids=["kb2"],
                chunks=chunks,
                top_n=1,
            )
        )

        assert (
            len(fake.calls) == 2
        )  # 再次调 LLM，因为 frozenset({"kb1"}) ≠ frozenset({"kb2"})

    def test_frozenset_kb1kb2_not_hit_kb1(self):
        """frozenset({"kb1","kb2"}) 缓存不命中 frozenset({"kb1"})。"""
        from ragnexus.adapters.rerank.llm import LLMRerankProvider

        fake = FakeLLMProvider()
        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        query_vector = [0.1] * 10
        chunks = [make_hit("c_1", score=0.9, text="text 1")]

        fake.responses.append({"rankings": [{"chunk_id": "c_1", "rerank_score": 0.8}]})
        asyncio.run(
            provider.rerank(
                query="测试",
                query_vector=query_vector,
                kb_ids=["kb1", "kb2"],
                chunks=chunks,
                top_n=1,
            )
        )
        assert len(fake.calls) == 1

        # 第二次：kb_ids=["kb1"] → frozenset({"kb1"}) ≠ frozenset({"kb1","kb2"})
        fake.responses.append({"rankings": [{"chunk_id": "c_1", "rerank_score": 0.7}]})
        asyncio.run(
            provider.rerank(
                query="测试",
                query_vector=query_vector,
                kb_ids=["kb1"],
                chunks=chunks,
                top_n=1,
            )
        )

        assert len(fake.calls) == 2  # 再次调 LLM，因为 frozenset 键不同

    def test_clear_cache_kb1_removes_compound_key(self):
        """clear_cache("kb1") 只清空包含 kb1 的 frozenset 条目。"""
        import time
        from ragnexus.adapters.rerank.llm import LLMRerankProvider, CacheEntry

        fake = FakeLLMProvider()
        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]

        query_vector = [0.1] * 10
        now = time.time()

        # 手动构造三个 frozenset 键的缓存条目
        entry_kb1 = CacheEntry(
            query_embedding=query_vector,
            query_text="测试1",
            rankings={"c_1": 0.9},
            timestamp=now,
        )
        entry_kb2 = CacheEntry(
            query_embedding=query_vector,
            query_text="测试2",
            rankings={"c_2": 0.8},
            timestamp=now,
        )
        entry_kb1kb3 = CacheEntry(
            query_embedding=query_vector,
            query_text="测试3",
            rankings={"c_3": 0.7},
            timestamp=now,
        )

        provider._cache[frozenset({"kb1"})] = [entry_kb1]
        provider._cache[frozenset({"kb2"})] = [entry_kb2]
        provider._cache[frozenset({"kb1", "kb3"})] = [entry_kb1kb3]

        assert len(provider._cache) == 3

        # clear_cache("kb1") 应删除 frozenset({"kb1"}) 和 frozenset({"kb1","kb3"})
        asyncio.run(provider.clear_cache("kb1"))

        assert frozenset({"kb1"}) not in provider._cache
        assert frozenset({"kb1", "kb3"}) not in provider._cache
        assert frozenset({"kb2"}) in provider._cache
        assert len(provider._cache) == 1

        # 行为验证：kb2 缓存仍有效（不调 LLM）
        chunks_kb2 = [make_hit("c_2", score=0.9, text="text 2")]
        asyncio.run(
            provider.rerank(
                query="测试2",
                query_vector=query_vector,
                kb_ids=["kb2"],
                chunks=chunks_kb2,
                top_n=1,
            )
        )
        assert len(fake.calls) == 0

        # kb1 缓存已清除 → 需要调 LLM
        fake.responses.append({"rankings": [{"chunk_id": "c_1", "rerank_score": 0.9}]})
        chunks_kb1 = [make_hit("c_1", score=0.9, text="text 1")]
        asyncio.run(
            provider.rerank(
                query="测试1",
                query_vector=query_vector,
                kb_ids=["kb1"],
                chunks=chunks_kb1,
                top_n=1,
            )
        )
        assert len(fake.calls) == 1
