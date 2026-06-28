"""LLMRewriteProvider 单元测试。

测试场景：
- 构造器参数存储
- rewrite 正常流程（needs_rewrite=true）
- rewrite 不需要改写（needs_rewrite=false）
- 缓存命中（相同语义 query 跳过 LLM）
- JSON 5 层防御（markdown 包裹、无效 JSON、缺字段）
- 降级（LLM 异常 → 返回原始 query）
- 降级（JSON 解析全失败 → 返回原始 query）
- clear_cache 清空指定 KB
- reason 字段仅日志不影响逻辑
- 二次精炼（rewritten_query > 200 字）
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ragnexus.adapters.llm.base import LLMProvider
from ragnexus.domain.ports import RewriteResult

# ============================================================================
# Fake / Stub 类
# ============================================================================


class FakeLLMProvider(LLMProvider):
    """模拟 LLMProvider：按预制 responses 顺序返回 JSON。"""

    def __init__(self, responses: list[dict] | None = None):
        self.responses = responses or []
        self.call_count = 0
        self._call_args: list[dict] = []

    async def chat_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict,
        temperature: float = 0.0,
        timeout_seconds: int | None = None,
    ) -> dict:
        self._call_args.append(
            {
                "system_prompt": system_prompt,
                "user_payload": user_payload,
                "temperature": temperature,
                "timeout_seconds": timeout_seconds,
            }
        )
        idx = self.call_count
        self.call_count += 1
        if idx < len(self.responses):
            return self.responses[idx]
        raise RuntimeError(f"FakeLLMProvider 用完了预置响应（索引 {idx}）")


class FakeEmbedder:
    """模拟 EmbedderPort：单个文本返回固定向量，多个文本返回固定向量列表。"""

    def __init__(self, fixed_vector: list[float] | None = None):
        self._fixed_vector = fixed_vector or [0.1, 0.2, 0.3]
        self.embed_calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(texts)
        return [self._fixed_vector] * len(texts)


# ============================================================================
# 导入被测类
# ============================================================================

from ragnexus.adapters.rewrite.llm import LLMRewriteProvider  # noqa: E402

# ============================================================================
# 测试
# ============================================================================


class TestConstructor:
    """构造器参数存储测试。"""

    def test_constructor_stores_defaults(self):
        """构造器使用默认值时应存储所有参数。"""
        llm = FakeLLMProvider()
        embedder = FakeEmbedder()
        provider = LLMRewriteProvider(llm=llm, embedder=embedder)

        assert provider.llm is llm
        assert provider.embedder is embedder
        assert provider.cache_similarity_threshold == 0.95
        assert provider.cache_max_entries == 100
        assert provider.cache_ttl_seconds == 300
        assert provider.temperature == 0.0

    def test_constructor_stores_custom_values(self):
        """构造器使用自定义值时应存储所有参数。"""
        llm = FakeLLMProvider()
        embedder = FakeEmbedder()
        provider = LLMRewriteProvider(
            llm=llm,
            embedder=embedder,
            cache_similarity_threshold=0.9,
            cache_max_entries=50,
            cache_ttl_seconds=600,
            temperature=0.3,
        )

        assert provider.cache_similarity_threshold == 0.9
        assert provider.cache_max_entries == 50
        assert provider.cache_ttl_seconds == 600
        assert provider.temperature == 0.3


class TestRewriteNormal:
    """rewrite 正常流程测试。"""

    @pytest.mark.asyncio
    async def test_rewrite_needs_rewrite(self):
        """LLM 返回 needs_rewrite=true 时，改写 query。"""
        llm = FakeLLMProvider(
            responses=[
                {
                    "needs_rewrite": True,
                    "rewritten_query": "退款政策 申请条件 流程",
                    "reason": "包含指代词'上次那个'",
                }
            ]
        )
        embedder = FakeEmbedder()
        provider = LLMRewriteProvider(llm=llm, embedder=embedder)

        result = await provider.rewrite(query="上次那个退款的事", kb_ids=["kb1"])

        assert result.original_query == "上次那个退款的事"
        assert result.rewritten_query == "退款政策 申请条件 流程"
        assert result.needs_rewrite is True
        assert "指代词" in result.reason

    @pytest.mark.asyncio
    async def test_rewrite_no_rewrite_needed(self):
        """LLM 返回 needs_rewrite=false 时，不改写。"""
        llm = FakeLLMProvider(
            responses=[
                {
                    "needs_rewrite": False,
                    "rewritten_query": None,
                    "reason": "查询已包含具体关键词",
                }
            ]
        )
        embedder = FakeEmbedder()
        provider = LLMRewriteProvider(llm=llm, embedder=embedder)

        result = await provider.rewrite(query="退款政策 申请条件", kb_ids=["kb1"])

        assert result.original_query == "退款政策 申请条件"
        assert result.rewritten_query == "退款政策 申请条件"
        assert result.needs_rewrite is False
        assert "关键词" in result.reason


class TestCacheHit:
    """缓存测试。"""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_llm(self):
        """相同语义 query 第二次调用应命中缓存，跳过 LLM。"""
        llm = FakeLLMProvider(
            responses=[
                {
                    "needs_rewrite": True,
                    "rewritten_query": "退款流程 步骤",
                    "reason": "口语化",
                }
            ]
        )
        # 使用相同向量，确保余弦相似度 = 1.0，一定命中缓存
        embedder = FakeEmbedder(fixed_vector=[1.0, 0.0, 0.0])
        provider = LLMRewriteProvider(llm=llm, embedder=embedder)

        # 第一次调用 — 走 LLM
        result1 = await provider.rewrite(query="怎么退款", kb_ids=["kb1"])
        assert result1.rewritten_query == "退款流程 步骤"
        assert llm.call_count == 1

        # 第二次调用相同 query — 应命中缓存，不调用 LLM
        result2 = await provider.rewrite(query="怎么退款", kb_ids=["kb1"])
        assert result2.rewritten_query == "退款流程 步骤"
        assert llm.call_count == 1  # 仍然为 1，未增加

    @pytest.mark.asyncio
    async def test_different_kb_no_cross_cache(self):
        """不同 KB 之间缓存隔离。"""
        llm = FakeLLMProvider(
            responses=[
                {
                    "needs_rewrite": True,
                    "rewritten_query": "退款流程",
                    "reason": "口语化",
                },
                {
                    "needs_rewrite": True,
                    "rewritten_query": "退货说明",
                    "reason": "口语化",
                },
            ]
        )
        embedder = FakeEmbedder(fixed_vector=[1.0, 0.0, 0.0])
        provider = LLMRewriteProvider(llm=llm, embedder=embedder)

        r1 = await provider.rewrite(query="怎么退款", kb_ids=["kb1"])
        r2 = await provider.rewrite(query="怎么退款", kb_ids=["kb2"])

        # 两个 KB 各自走一次 LLM（缓存未命中，因为 KB 不同）
        assert llm.call_count == 2
        assert r1.rewritten_query == "退款流程"
        assert r2.rewritten_query == "退货说明"


class TestJsonDefense:
    """JSON 5 层防御测试。"""

    @pytest.mark.asyncio
    async def test_layer2_markdown_wrapped_json(self):
        """Layer 2：正则提取 ```json ... ``` 包裹的 JSON。"""
        from ragnexus.adapters.rewrite.llm import _parse_rewrite_json

        raw = '```json\n{"needs_rewrite": true, "rewritten_query": "测试改写", "reason": "OK"}\n```'
        result = _parse_rewrite_json(raw)
        assert result["needs_rewrite"] is True
        assert result["rewritten_query"] == "测试改写"

    @pytest.mark.asyncio
    async def test_layer3_outer_braces_extract(self):
        """Layer 3：正则提取最外层 {...}。"""
        from ragnexus.adapters.rewrite.llm import _parse_rewrite_json

        raw = '前缀文本 {"needs_rewrite": false, "rewritten_query": null, "reason": "清晰"} 后缀'
        result = _parse_rewrite_json(raw)
        assert result["needs_rewrite"] is False
        assert result["reason"] == "清晰"

    @pytest.mark.asyncio
    async def test_layer4_schema_validation_missing_field(self):
        """Layer 4：缺 needs_rewrite 字段 → 降级。"""
        from ragnexus.adapters.rewrite.llm import _parse_rewrite_json

        raw = '{"rewritten_query": "xxx", "reason": "yyy"}'
        result = _parse_rewrite_json(raw)
        # 降级应返回降级 dict
        assert result.get("_degraded") is True

    @pytest.mark.asyncio
    async def test_layer4_needs_rewrite_true_requires_rewritten_query(self):
        """Layer 4：needs_rewrite=true 但 rewritten_query 为 null → 降级。"""
        from ragnexus.adapters.rewrite.llm import _parse_rewrite_json

        raw = '{"needs_rewrite": true, "rewritten_query": null, "reason": ""}'
        result = _parse_rewrite_json(raw)
        assert result.get("_degraded") is True

    @pytest.mark.asyncio
    async def test_total_parse_failure_degradation(self):
        """全部 JSON 解析层失败 → 降级返回原始 query。"""
        llm = FakeLLMProvider(responses=[{"some": "data"}])
        embedder = FakeEmbedder()
        provider = LLMRewriteProvider(llm=llm, embedder=embedder)

        # 模拟 _parse_rewrite_json 返回降级标记
        with patch(
            "ragnexus.adapters.rewrite.llm._parse_rewrite_json",
            return_value={"_degraded": True, "reason": "JSON 解析全部失败"},
        ):
            result = await provider.rewrite(query="原始查询", kb_ids=["kb1"])

        assert result.original_query == "原始查询"
        assert result.rewritten_query == "原始查询"
        assert result.needs_rewrite is False
        assert "JSON" in result.reason


class TestDegradation:
    """降级测试。"""

    @pytest.mark.asyncio
    async def test_llm_exception_returns_original(self):
        """LLM 抛异常 → 降级返回原始 query。"""
        llm = FakeLLMProvider()
        # 让 chat_json 抛出异常
        llm.chat_json = AsyncMock(side_effect=Exception("LLM 超时"))
        embedder = FakeEmbedder()
        provider = LLMRewriteProvider(llm=llm, embedder=embedder)

        result = await provider.rewrite(query="原始查询", kb_ids=["kb1"])

        assert result.original_query == "原始查询"
        assert result.rewritten_query == "原始查询"
        assert result.needs_rewrite is False
        assert (
            "失败" in result.reason
            or "超时" in result.reason
            or "异常" in result.reason
        )

    @pytest.mark.asyncio
    async def test_embed_exception_returns_original(self):
        """Embedder 抛异常 → 降级返回原始 query（缓存查找失败不阻断流程）。"""
        llm = FakeLLMProvider()
        embedder = FakeEmbedder()
        embedder.embed = AsyncMock(side_effect=Exception("Embedder 不可用"))
        provider = LLMRewriteProvider(llm=llm, embedder=embedder)

        result = await provider.rewrite(query="原始查询", kb_ids=["kb1"])

        # 缓存查找失败不应阻断，应继续走 LLM
        # 但因为 LLM 也没有响应，全链路降级
        assert result.original_query == "原始查询"
        assert result.rewritten_query == "原始查询"


class TestClearCache:
    """clear_cache 测试。"""

    @pytest.mark.asyncio
    async def test_clear_cache_removes_kb(self):
        """clear_cache 清空指定 KB 的缓存。"""
        llm = FakeLLMProvider(
            responses=[
                {"needs_rewrite": True, "rewritten_query": "改写1", "reason": "口语化"},
                {"needs_rewrite": True, "rewritten_query": "改写2", "reason": "口语化"},
            ]
        )
        embedder = FakeEmbedder(fixed_vector=[1.0, 0.0, 0.0])
        provider = LLMRewriteProvider(llm=llm, embedder=embedder)

        # 缓存一个结果
        await provider.rewrite(query="查询A", kb_ids=["kb1"])
        assert llm.call_count == 1

        # clear_cache 清空 kb1
        await provider.clear_cache("kb1")

        # 再次查询同一 query — 缓存已清空，应重新调用 LLM
        result = await provider.rewrite(query="查询A", kb_ids=["kb1"])
        assert result.rewritten_query == "改写2"
        assert llm.call_count == 2  # 重新调用了 LLM

    @pytest.mark.asyncio
    async def test_clear_cache_does_not_affect_other_kb(self):
        """clear_cache 不影响其他 KB 的缓存。"""
        llm = FakeLLMProvider(
            responses=[
                {"needs_rewrite": True, "rewritten_query": "改写1", "reason": "口语化"},
                {"needs_rewrite": True, "rewritten_query": "改写1", "reason": "口语化"},
                {"needs_rewrite": True, "rewritten_query": "改写2", "reason": "口语化"},
            ]
        )
        embedder = FakeEmbedder(fixed_vector=[1.0, 0.0, 0.0])
        provider = LLMRewriteProvider(llm=llm, embedder=embedder)

        await provider.rewrite(query="查询A", kb_ids=["kb1"])
        await provider.rewrite(query="查询A", kb_ids=["kb2"])
        assert llm.call_count == 2

        # 清空 kb1
        await provider.clear_cache("kb1")

        r2 = await provider.rewrite(query="查询A", kb_ids=["kb2"])
        assert r2.rewritten_query == "改写1"
        assert llm.call_count == 2  # kb2 命中缓存，未调 LLM
        r1 = await provider.rewrite(query="查询A", kb_ids=["kb1"])
        assert r1.rewritten_query == "改写2"
        assert llm.call_count == 3  # kb1 缓存已清，重新调 LLM


class TestReasonLoggingOnly:
    """reason 字段仅日志使用，不影响业务逻辑。"""

    @pytest.mark.asyncio
    async def test_reason_not_used_in_business_logic(self):
        """验证 reason 不影响业务逻辑 — 只出现在日志中。"""
        llm = FakeLLMProvider(
            responses=[
                {
                    "needs_rewrite": True,
                    "rewritten_query": "改写后的查询",
                    "reason": "任意原因 — 不影响改写结果",
                }
            ]
        )
        embedder = FakeEmbedder()
        provider = LLMRewriteProvider(llm=llm, embedder=embedder)

        result = await provider.rewrite(query="原始查询", kb_ids=["kb1"])

        # 业务逻辑只看 needs_rewrite 和 rewritten_query
        assert result.needs_rewrite is True
        assert result.rewritten_query == "改写后的查询"
        # reason 存在，但仅用于日志
        assert result.reason == "任意原因 — 不影响改写结果"


class TestSecondPassRefinement:
    """二次精炼测试。"""

    @pytest.mark.asyncio
    async def test_overly_long_rewrite_triggers_refinement(self):
        """rewritten_query > 200 字时触发二次精炼。"""
        long_text = "这是一个非常长的改写结果" * 20  # ~300 字
        assert len(long_text) > 200

        refined = "精炼后的短文本"
        llm = FakeLLMProvider(
            responses=[
                {
                    "needs_rewrite": True,
                    "rewritten_query": long_text,
                    "reason": "详细改写",
                },
                {"rewritten_query": refined},
            ]
        )
        embedder = FakeEmbedder()
        provider = LLMRewriteProvider(llm=llm, embedder=embedder)

        result = await provider.rewrite(query="原始查询", kb_ids=["kb1"])

        assert result.rewritten_query == refined
        assert result.needs_rewrite is True
        assert llm.call_count == 2  # 主调用 + 精炼调用

    @pytest.mark.asyncio
    async def test_refinement_failure_degradation(self):
        """二次精炼失败 → 降级返回原始 query。"""
        long_text = "x" * 250  # > 200 字
        llm = FakeLLMProvider()
        llm.chat_json = AsyncMock(
            side_effect=[
                {"needs_rewrite": True, "rewritten_query": long_text, "reason": "过长"},
                Exception("精炼调用失败"),
            ]
        )
        embedder = FakeEmbedder()
        provider = LLMRewriteProvider(llm=llm, embedder=embedder)

        result = await provider.rewrite(query="原始查询", kb_ids=["kb1"])

        assert result.original_query == "原始查询"
        assert result.rewritten_query == "原始查询"
        assert result.needs_rewrite is False


class TestAlwaysNoException:
    """rewrite 永不抛异常测试。"""

    @pytest.mark.asyncio
    async def test_rewrite_never_raises(self):
        """无论发生什么，rewrite() 永不抛异常。"""
        llm = FakeLLMProvider()
        llm.chat_json = AsyncMock(side_effect=RuntimeError("模拟崩溃"))
        embedder = FakeEmbedder()
        embedder.embed = AsyncMock(side_effect=RuntimeError("Embedder 崩溃"))
        provider = LLMRewriteProvider(llm=llm, embedder=embedder)

        # 不应抛出任何异常
        result = await provider.rewrite(query="test", kb_ids=["kb1"])

        assert isinstance(result, RewriteResult)
        assert result.original_query == "test"
        assert result.rewritten_query == "test"
        assert result.needs_rewrite is False
