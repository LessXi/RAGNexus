"""集成测试：RetrieveUseCase 全链路（Rewrite + Rerank 组合）。

使用 mock 的 Port 实现 — 不需要真实数据库。
测试场景:
  1. 同时启用 Rewrite + Rerank
  2. 同时禁用两者
  3. 只启用 Rewrite
  4. 只启用 Rerank
  5. candidate_k 计算
"""

import pytest

from ragnexus.adapters.rerank.noop import NoopRerankProvider
from ragnexus.adapters.rewrite.noop import NoopRewriteProvider
from ragnexus.application.retrieve_use_case import RetrieveUseCase
from ragnexus.domain.models import SearchHit
from ragnexus.domain.ports import RewriteResult


# ═══════════════════════════════════════════════════════════════════
# Fake/Mock 实现 — 提供可控行为，不依赖外部服务
# ═══════════════════════════════════════════════════════════════════


class FakeKBRepo:
    """假 KB 仓库 — 所有 KB 均存在。"""

    async def exists(self, kb_id: str) -> bool:
        return True


class FakeEmbedder:
    """假 Embedder — 返回固定向量。原始 query 和改写 query 用不同 prefix。"""

    def __init__(self, prefix: float = 1.0):
        self.prefix = prefix
        self.call_count = 0
        self.last_texts: list[str] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        self.last_texts = texts
        return [[self.prefix] * 8 for _ in texts]


class FakeVectorStore:
    """假向量存储 — 返回固定的 SearchHit 列表。"""

    def __init__(self, hits: list[SearchHit] | None = None):
        self.hits = hits or _make_hits(20)
        self.search_call_count = 0
        self.last_kwargs: dict = {}

    async def search_by_vector(
        self,
        query_vector: list[float],
        top_k: int,
        kb_ids: list[str],
    ) -> list[SearchHit]:
        self.search_call_count += 1
        self.last_kwargs = {
            "query_vector": query_vector,
            "top_k": top_k,
            "kb_ids": kb_ids,
        }
        return self.hits[:top_k]


class FakeLogPort:
    """假日志端口 — 记录调用但不执行 IO。"""

    def __init__(self):
        self.logs: list[dict] = []

    async def log(self, *, query, kb_ids, top_k, hit_count, latency_ms):
        self.logs.append(
            {
                "query": query,
                "kb_ids": kb_ids,
                "top_k": top_k,
                "hit_count": hit_count,
                "latency_ms": latency_ms,
            }
        )


class FakeReranker:
    """假 Reranker — 对 chunks 反转 + 调整 score 来模拟重排。"""

    def __init__(self):
        self.rerank_call_count = 0
        self.last_kwargs: dict = {}

    async def rerank(self, *, query, query_vector, kb_ids, chunks, top_n):
        self.rerank_call_count += 1
        self.last_kwargs = {
            "query": query,
            "query_vector": query_vector,
            "kb_ids": kb_ids,
            "chunk_count": len(chunks),
            "top_n": top_n,
        }
        return list(reversed(chunks[:top_n]))

    async def clear_cache(self, kb_id: str) -> None:
        pass


class FakeRewriter:
    """假 Rewriter — 把 query 改写成带前缀的形式。"""

    def __init__(self):
        self.rewrite_call_count = 0
        self.last_kwargs: dict = {}

    async def rewrite(self, *, query, kb_ids):
        self.rewrite_call_count += 1
        self.last_kwargs = {"query": query, "kb_ids": kb_ids}
        return RewriteResult(
            original_query=query,
            rewritten_query=f"technical definition of {query}",
            needs_rewrite=True,
            reason="假改写",
        )

    async def clear_cache(self, kb_id: str) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def _make_hits(count: int) -> list[SearchHit]:
    """生成 count 个 SearchHit，score 递减。"""
    return [
        SearchHit(
            chunk_id=f"kb_test:{i}",
            kb_id="kb_test",
            doc_id=f"doc_{i // 5}",
            score=float(1.0 - i * 0.04),
            text=f"Chunk text number {i}",
            metadata={"index": i},
        )
        for i in range(count)
    ]


def _build_use_case(
    *,
    reranker=None,
    rewriter=None,
    candidate_multiplier: int = 1,
    min_candidates: int = 0,
    embedder=None,
    store=None,
):
    """构建 RetrieveUseCase — 所有依赖可通过参数注入。"""
    return RetrieveUseCase(
        kb_repo=FakeKBRepo(),
        embedder=embedder or FakeEmbedder(),
        store=store or FakeVectorStore(),
        log_port=FakeLogPort(),
        reranker=reranker or NoopRerankProvider(),
        rewriter=rewriter or NoopRewriteProvider(),
        candidate_multiplier=candidate_multiplier,
        min_candidates=min_candidates,
    )


# ═══════════════════════════════════════════════════════════════════
# 场景 1: 同时启用 Rewrite + Rerank
# ═══════════════════════════════════════════════════════════════════


class TestBothRewriteAndRerankEnabled:
    """同时启用 Rewrite + Rerank 时验证完整数据流。

    数据流: rewrite → embed(改写query) → search → rerank → return
    """

    @pytest.mark.asyncio
    async def test_data_flow_order(self):
        """各步骤按正确顺序调用，且参数正确传递。"""
        embedder = FakeEmbedder(prefix=1.0)
        store = FakeVectorStore()
        reranker = FakeReranker()
        rewriter = FakeRewriter()

        uc = _build_use_case(
            reranker=reranker,
            rewriter=rewriter,
            embedder=embedder,
            store=store,
        )

        await uc.execute(query="hello world", kb_ids=["kb_test"], top_k=5)

        # 1. rewriter.rewrite 被调用
        assert rewriter.rewrite_call_count == 1
        assert rewriter.last_kwargs["query"] == "hello world"
        assert rewriter.last_kwargs["kb_ids"] == ["kb_test"]

        # 2. embedder.embed 使用改写后的 query
        assert embedder.call_count == 1
        assert embedder.last_texts == ["technical definition of hello world"]

        # 3. store.search_by_vector 使用 candidate_k=5 (multiplier=1)
        assert store.search_call_count == 1
        assert store.last_kwargs["top_k"] == 5
        assert store.last_kwargs["kb_ids"] == ["kb_test"]

        # 4. reranker.rerank 被调用，query 是原始 query
        assert reranker.rerank_call_count == 1
        assert reranker.last_kwargs["query"] == "hello world"
        assert reranker.last_kwargs["top_n"] == 5

    @pytest.mark.asyncio
    async def test_reranker_output_is_returned(self):
        """execute() 返回 rerank 后的结果，而非原始向量召回结果。"""
        hits = _make_hits(10)
        store = FakeVectorStore(hits=hits)
        reranker = FakeReranker()
        rewriter = FakeRewriter()

        uc = _build_use_case(
            reranker=reranker,
            rewriter=rewriter,
            store=store,
        )

        result = await uc.execute(query="query", kb_ids=["kb_test"], top_k=5)

        # FakeReranker 反转了前 top_n 个结果
        # 原始: [h0, h1, h2, h3, h4], 反转后: [h4, h3, h2, h1, h0]
        assert len(result) == 5
        assert result[0].chunk_id == "kb_test:4"
        assert result[4].chunk_id == "kb_test:0"

    @pytest.mark.asyncio
    async def test_rerank_uses_original_query(self):
        """reranker.rerank 接收原始 query（非改写后）。"""
        reranker = FakeReranker()
        rewriter = FakeRewriter()

        uc = _build_use_case(reranker=reranker, rewriter=rewriter)

        await uc.execute(query="原始查询语句", kb_ids=["kb_test"], top_k=5)
        assert reranker.last_kwargs["query"] == "原始查询语句"


# ═══════════════════════════════════════════════════════════════════
# 场景 2: 同时禁用 Rewrite 和 Rerank
# ═══════════════════════════════════════════════════════════════════


class TestBothDisabled:
    """同时禁用 Rewrite + Rerank 时验证直通行为。

    数据流: embed(原始query) → search → return
    """

    @pytest.mark.asyncio
    async def test_direct_flow(self):
        """禁用两者时，embed 用原始 query，search 结果直接返回。"""
        embedder = FakeEmbedder(prefix=1.0)
        store = FakeVectorStore()

        uc = _build_use_case(
            reranker=NoopRerankProvider(),
            rewriter=NoopRewriteProvider(),
            embedder=embedder,
            store=store,
        )

        result = await uc.execute(
            query="direct query",
            kb_ids=["kb_test"],
            top_k=3,
        )

        # embed 使用原始 query
        assert embedder.call_count == 1
        assert embedder.last_texts == ["direct query"]

        # search 使用原始 top_k（无 candidate_k 放大）
        assert store.search_call_count == 1
        assert store.last_kwargs["top_k"] == 3

        # 返回结果长度 == top_k
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_noop_rewriter_returns_original_query(self):
        """NoopRewriteProvider.rewrite 返回 rewritten_query == original_query。"""
        noop = NoopRewriteProvider()
        result = await noop.rewrite(query="test query", kb_ids=["kb1"])
        assert result.original_query == "test query"
        assert result.rewritten_query == "test query"
        assert result.needs_rewrite is False

    @pytest.mark.asyncio
    async def test_noop_reranker_preserves_chunks(self):
        """NoopRerankProvider.rerank 按 top_n 截断但不修改顺序。"""
        hits = _make_hits(10)
        noop = NoopRerankProvider()

        result = await noop.rerank(
            query="test",
            query_vector=[0.5] * 8,
            kb_ids=["kb1"],
            chunks=hits,
            top_n=3,
        )

        assert len(result) == 3
        # 保持原始顺序
        assert result[0].chunk_id == hits[0].chunk_id
        assert result[1].chunk_id == hits[1].chunk_id
        assert result[2].chunk_id == hits[2].chunk_id


# ═══════════════════════════════════════════════════════════════════
# 场景 3: 只启用 Rewrite（禁用 Rerank）
# ═══════════════════════════════════════════════════════════════════


class TestRewriteOnly:
    """只启用 Rewrite 时验证数据流。

    数据流: rewrite → embed(改写query) → search → return (经 NoopRerank)
    """

    @pytest.mark.asyncio
    async def test_rewritten_query_used_for_embed(self):
        """embed 使用改写后的 query，而非原始 query。"""
        embedder = FakeEmbedder(prefix=1.0)
        rewriter = FakeRewriter()

        uc = _build_use_case(
            reranker=NoopRerankProvider(),
            rewriter=rewriter,
            embedder=embedder,
        )

        await uc.execute(query="what is AI", kb_ids=["kb_test"], top_k=5)
        assert embedder.last_texts == ["technical definition of what is AI"]

    @pytest.mark.asyncio
    async def test_result_length_matches_top_k(self):
        """禁用 rerank 时，返回结果数 == top_k。"""
        rewriter = FakeRewriter()

        uc = _build_use_case(
            reranker=NoopRerankProvider(),
            rewriter=rewriter,
        )

        result = await uc.execute(
            query="test",
            kb_ids=["kb_test"],
            top_k=3,
        )
        assert len(result) == 3


# ═══════════════════════════════════════════════════════════════════
# 场景 4: 只启用 Rerank（禁用 Rewrite）
# ═══════════════════════════════════════════════════════════════════


class TestRerankOnly:
    """只启用 Rerank 时验证数据流。

    数据流: embed(原始query) → search → rerank → return
    """

    @pytest.mark.asyncio
    async def test_original_query_used_for_embed(self):
        """禁用 rewrite 时，embed 使用原始 query。"""
        embedder = FakeEmbedder(prefix=1.0)
        reranker = FakeReranker()

        uc = _build_use_case(
            reranker=reranker,
            rewriter=NoopRewriteProvider(),
            embedder=embedder,
        )

        await uc.execute(
            query="original query xyz",
            kb_ids=["kb_test"],
            top_k=5,
        )
        assert embedder.last_texts == ["original query xyz"]

    @pytest.mark.asyncio
    async def test_rerank_receives_original_query(self):
        """reranker 接收原始 query 做相关性判断。"""
        reranker = FakeReranker()

        uc = _build_use_case(
            reranker=reranker,
            rewriter=NoopRewriteProvider(),
        )

        await uc.execute(
            query="how to cook pasta",
            kb_ids=["kb_test"],
            top_k=5,
        )
        assert reranker.last_kwargs["query"] == "how to cook pasta"

    @pytest.mark.asyncio
    async def test_rerank_modifies_result(self):
        """启用 rerank 时返回结果被 reranker 修改。"""
        hits = _make_hits(10)
        store = FakeVectorStore(hits=hits)
        reranker = FakeReranker()

        uc = _build_use_case(
            reranker=reranker,
            rewriter=NoopRewriteProvider(),
            store=store,
        )

        result = await uc.execute(query="query", kb_ids=["kb_test"], top_k=5)
        # FakeReranker 反转: [h4, h3, h2, h1, h0]
        assert result[0].chunk_id == "kb_test:4"


# ═══════════════════════════════════════════════════════════════════
# 场景 5: candidate_k 计算
# ═══════════════════════════════════════════════════════════════════


class TestCandidateK:
    """验证 candidate_k 计算 — 启用 rerank 时放大搜索候选。"""

    @pytest.mark.asyncio
    async def test_multiplier_only(self):
        """candidate_multiplier=3 → candidate_k = top_k * 3。"""
        store = FakeVectorStore()
        reranker = FakeReranker()

        uc = _build_use_case(
            reranker=reranker,
            rewriter=NoopRewriteProvider(),
            store=store,
            candidate_multiplier=3,
            min_candidates=0,
        )

        await uc.execute(query="test", kb_ids=["kb_test"], top_k=5)
        assert store.last_kwargs["top_k"] == 15  # 5 * 3

    @pytest.mark.asyncio
    async def test_min_candidates_only(self):
        """min_candidates=10 → candidate_k = top_k + 10。"""
        store = FakeVectorStore()
        reranker = FakeReranker()

        uc = _build_use_case(
            reranker=reranker,
            rewriter=NoopRewriteProvider(),
            store=store,
            candidate_multiplier=1,
            min_candidates=10,
        )

        await uc.execute(query="test", kb_ids=["kb_test"], top_k=3)
        assert store.last_kwargs["top_k"] == 13  # 3 + 10

    @pytest.mark.asyncio
    async def test_both_takes_max(self):
        """multiplier*top_k=10, min_candidates+top_k=7 → max=10。"""
        store = FakeVectorStore()
        reranker = FakeReranker()

        uc = _build_use_case(
            reranker=reranker,
            rewriter=NoopRewriteProvider(),
            store=store,
            candidate_multiplier=2,
            min_candidates=2,
        )

        await uc.execute(query="test", kb_ids=["kb_test"], top_k=5)
        assert store.last_kwargs["top_k"] == 10

    @pytest.mark.asyncio
    async def test_candidate_k_still_computed_when_rerank_disabled(self):
        """禁用 rerank 时 candidate_k 公式仍生效。NoopRerankProvider 按 top_n 截断。"""
        store = FakeVectorStore()

        uc = _build_use_case(
            reranker=NoopRerankProvider(),
            rewriter=NoopRewriteProvider(),
            store=store,
            candidate_multiplier=3,
            min_candidates=10,
        )

        await uc.execute(query="test", kb_ids=["kb_test"], top_k=5)
        # search 用 candidate_k=15 (max(5*3, 5+10)=15)
        assert store.last_kwargs["top_k"] == 15

    @pytest.mark.asyncio
    async def test_default_multiplier_is_1(self):
        """默认 candidate_multiplier=1 → candidate_k == top_k。"""
        store = FakeVectorStore()

        uc = _build_use_case(
            reranker=NoopRerankProvider(),
            rewriter=NoopRewriteProvider(),
            store=store,
        )

        await uc.execute(query="test", kb_ids=["kb_test"], top_k=10)
        assert store.last_kwargs["top_k"] == 10
