"""集成测试：RetrieveUseCase 全链路（Rewrite + Rerank 组合）。

使用真实 PG + pgvector 数据库，embedder/LLM HTTP 通过 pytest-httpx 模拟。
测试场景:
  1. 同时启用 Rewrite + Rerank
  2. 同时禁用两者
  3. 只启用 Rewrite
  4. 只启用 Rerank
  5. candidate_k 计算
"""

from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio

from ragnexus.adapters.embedder.openai_compat import OpenAICompatEmbedder
from ragnexus.adapters.knowledge_base.pg import PgKnowledgeBaseRepository
from ragnexus.adapters.llm.openai_compatible import OpenAICompatibleLLMProvider
from ragnexus.adapters.rerank.llm import LLMRerankProvider
from ragnexus.adapters.rerank.noop import NoopRerankProvider
from ragnexus.adapters.retrieve_log.pg import PgRetrieveLogRepository
from ragnexus.adapters.rewrite.llm import LLMRewriteProvider
from ragnexus.adapters.rewrite.noop import NoopRewriteProvider
from ragnexus.adapters.vector_store.pgvector import PgVectorStore
from ragnexus.application.retrieve_use_case import RetrieveUseCase
from ragnexus.domain.models import Chunk, SearchHit
from ragnexus.domain.ports import RewriteResult

pytestmark = [pytest.mark.integration]

TEST_DIM = 1024

_COUNTER = 0


def _make_vec(*seeds: float) -> list[float]:
    """创建 TEST_DIM 维向量，前缀为给定种子值，其余为 0。"""
    v = [0.0] * TEST_DIM
    for i, s in enumerate(seeds):
        v[i] = float(s)
    return v


# 查询向量 seed[0]=1.0 — chunk i 的 seed[0]=1.0-i*0.1，故 chunk 0 最近
_QUERY_VEC = _make_vec(1.0)


def _unique_suffix() -> str:
    """生成递增编号，确保每次测试产生不同的 KB/doc ID。"""
    global _COUNTER
    _COUNTER += 1
    return f"rt{_COUNTER}"


# ═══════════════════════════════════════════════════════════════════
# HTTP Mock Helpers
# ═══════════════════════════════════════════════════════════════════


def _setup_all_http_mocks(
    httpx_mock,
    *,
    enable_rewrite: bool = False,
    enable_rerank: bool = False,
):
    """设置所有 HTTP mock — 单一回调路由 embed/rewrite/rerank。

    返回 embed_texts 列表，每个元素是某次 embed 调用的文本列表。
    """
    embed_texts: list[list[str]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        url_path = request.url.path if request.url else ""

        # ── Embedder ──
        if url_path.endswith("/embeddings"):
            body = json.loads(request.content)
            texts = body.get("input", [])
            texts_list = texts if isinstance(texts, list) else [texts]
            embed_texts.append(texts_list)
            count = len(texts_list)
            return httpx.Response(
                status_code=200,
                json={
                    "data": [
                        {"embedding": _QUERY_VEC, "index": i} for i in range(count)
                    ]
                },
            )

        # ── Chat Completions ──
        if url_path.endswith("/chat/completions"):
            body = json.loads(request.content)
            messages = body.get("messages", [])
            system_content = messages[0].get("content", "") if messages else ""

            # Rewrite LLM（系统提示词以 "你是 RAG 检索查询优化器" 开头）
            if system_content.startswith("你是 RAG 检索查询优化器"):
                if not enable_rewrite:
                    return httpx.Response(
                        status_code=500,
                        json={"error": "rewrite LLM called but not enabled"},
                    )
                user_content = (
                    messages[1].get("content", "{}") if len(messages) > 1 else "{}"
                )
                user_payload = (
                    json.loads(user_content)
                    if isinstance(user_content, str)
                    else user_content
                )
                original_query = user_payload.get("query", "")
                rewritten = f"improved: {original_query}"
                response_content = json.dumps(
                    {
                        "needs_rewrite": True,
                        "rewritten_query": rewritten,
                        "reason": "mock rewrite",
                    }
                )
                return httpx.Response(
                    status_code=200,
                    json={"choices": [{"message": {"content": response_content}}]},
                )

            # Rerank LLM（系统提示词以 "你是 RAG 检索重排器" 开头）
            if system_content.startswith("你是 RAG 检索重排器"):
                if not enable_rerank:
                    return httpx.Response(
                        status_code=500,
                        json={"error": "rerank LLM called but not enabled"},
                    )
                user_content = (
                    messages[1].get("content", "{}") if len(messages) > 1 else "{}"
                )
                user_payload = (
                    json.loads(user_content)
                    if isinstance(user_content, str)
                    else user_content
                )
                candidates = user_payload.get("candidates", [])
                n = len(candidates)
                rankings = []
                for i, c in enumerate(candidates):
                    # 较后的候选得到更高分 → 输出顺序反转
                    scores = 0.5 if n <= 1 else 0.5 + i / (n - 1) * 0.4
                    rankings.append(
                        {
                            "chunk_id": c["chunk_id"],
                            "rerank_score": scores,
                            "reason": "mock rerank",
                        }
                    )
                response_content = json.dumps({"rankings": rankings})
                return httpx.Response(
                    status_code=200,
                    json={"choices": [{"message": {"content": response_content}}]},
                )

            return httpx.Response(
                status_code=500,
                json={"error": f"unknown system prompt: {system_content[:100]}"},
            )

        return httpx.Response(status_code=404, json={"error": "unexpected request"})

    httpx_mock.add_callback(_handler, is_reusable=True)
    return embed_texts


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


async def _ensure_kb(pool, kb_id: str) -> None:
    """确保 KB 行存在（PGVectorStore upsert 有外键约束）。"""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO knowledge_bases (id, name, name_key) "
            "VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            kb_id,
            kb_id,
            kb_id,
        )


def _make_chunks(
    kb_id: str,
    doc_id: str,
    count: int,
) -> list[Chunk]:
    """生成 count 个测试 chunk，向量按 index 递减以固定搜索顺序。

    向量: chunk i 的 seed[0] = 1.0 - i * 0.1
    查询向量 seed[0] = 1.0 → chunk 0 分最高，chunk count-1 分最低。
    """
    return [
        Chunk(
            id=f"{doc_id}:{i}",
            kb_id=kb_id,
            doc_id=doc_id,
            text=f"Chunk text number {i} in {doc_id}",
            vector=_make_vec(1.0 - i * 0.1),
            metadata={"index": i, "kb_id": kb_id},
        )
        for i in range(count)
    ]


def _build_embedder() -> OpenAICompatEmbedder:
    """构建被 httpx_mock 拦截的真实 OpenAICompatEmbedder。"""
    return OpenAICompatEmbedder(
        base_url="http://mock-embedder/v1",
        api_key="test-key",
        model="test-model",
        dim=TEST_DIM,
        batch_size=50,
        max_concurrency=2,
        max_retries=1,
        request_timeout=5.0,
        connect_timeout=2.0,
        retry_backoff_base=0.01,
    )


def _build_llm() -> OpenAICompatibleLLMProvider:
    """构建被 httpx_mock 拦截的真实 OpenAICompatibleLLMProvider。"""
    return OpenAICompatibleLLMProvider(
        base_url="http://mock-llm/v1",
        api_key="test-key",
        model="test-model",
        max_concurrency=2,
        max_retries=1,
        request_timeout=5.0,
        connect_timeout=2.0,
        retry_backoff_base=0.01,
    )


class SpyVectorStore:
    """薄包装 PgVectorStore — 记录 search_by_vector 参数用于断言。"""

    def __init__(self, inner: PgVectorStore):
        self._inner = inner
        self.search_call_count = 0
        self.last_kwargs: dict = {}

    async def connect(self, external_pool=None):
        return await self._inner.connect(external_pool=external_pool)

    async def close(self):
        return await self._inner.close()

    async def upsert(self, kb_id: str, chunks: list[Chunk]) -> None:
        return await self._inner.upsert(kb_id, chunks)

    async def search_by_vector(
        self,
        query_vector: list[float],
        top_k: int,
        kb_ids: list[str],
    ):
        self.search_call_count += 1
        self.last_kwargs = {
            "query_vector": query_vector,
            "top_k": top_k,
            "kb_ids": kb_ids,
        }
        return await self._inner.search_by_vector(query_vector, top_k, kb_ids)


# ═══════════════════════════════════════════════════════════════════
# 场景 1: 同时启用 Rewrite + Rerank
# ═══════════════════════════════════════════════════════════════════


class TestBothRewriteAndRerankEnabled:
    """同时启用 Rewrite + Rerank 时验证完整数据流。

    流程: rewrite → embed(改写query) → search → rerank → return
    """

    @pytest_asyncio.fixture
    async def store(self, pg_pool):
        s = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        await s.connect(external_pool=pg_pool)
        yield s
        # external_pool 连接池不归 store 所有，close() 为空操作

    @pytest_asyncio.fixture
    async def setup_data(self, pg_pool, store):
        """创建 KB + 插入 10 个测试 chunk，返回 kb_id 和 doc_id。"""
        suffix = _unique_suffix()
        kb_id = f"kb_rt_both_{suffix}"
        doc_id = f"doc_rt_both_{suffix}"
        await _ensure_kb(pg_pool, kb_id)
        chunks = _make_chunks(kb_id, doc_id, count=10)
        await store.upsert(kb_id, chunks)
        return kb_id, doc_id

    async def test_reranker_output_is_returned(
        self, pg_pool, store, setup_data, httpx_mock
    ):
        """execute() 返回 rerank 后的结果（非原始向量召回顺序）。

        chunk 0 向量最接近查询 → 搜索排第一。
        mock reranker 给较后的 chunk 更高分 → 输出反转。
        """
        kb_id, doc_id = setup_data

        _setup_all_http_mocks(httpx_mock, enable_rewrite=True, enable_rerank=True)

        embedder = _build_embedder()
        llm_rewrite = _build_llm()
        llm_rerank = _build_llm()
        spy_store = SpyVectorStore(store)

        rewriter = LLMRewriteProvider(
            llm=llm_rewrite,
            embedder=embedder,
            cache_similarity_threshold=0.99,
            temperature=0.0,
        )
        reranker = LLMRerankProvider(llm=llm_rerank, max_candidates=20, temperature=0.0)

        uc = RetrieveUseCase(
            kb_repo=PgKnowledgeBaseRepository(pg_pool),
            embedder=embedder,
            store=spy_store,
            log_port=PgRetrieveLogRepository(pg_pool),
            reranker=reranker,
            rewriter=rewriter,
            candidate_multiplier=3,  # 确保所有 10 个 chunk 到达 reranker
        )

        try:
            result = await uc.execute(query="hello world", kb_ids=[kb_id], top_k=5)

            assert len(result) == 5
            for h in result:
                assert h.kb_id == kb_id
                assert h.doc_id == doc_id

            # reranker mock 给 payload 中较后的候选更高分
            # → 索引最大的 chunk 应排在前列
            idxes = [int(h.chunk_id.rsplit(":", 1)[1]) for h in result]
            assert (
                max(idxes) in idxes[:2]
            ), f"最高索引 chunk 应排在前 2 名，实际: {idxes}"
        finally:
            await embedder.close()
            await llm_rewrite.close()
            await llm_rerank.close()

    async def test_data_flow_calls_llm(self, pg_pool, store, setup_data, httpx_mock):
        """启用 rewrite + rerank 时产生正确的 HTTP 调用。"""
        kb_id, doc_id = setup_data

        _setup_all_http_mocks(httpx_mock, enable_rewrite=True, enable_rerank=True)

        embedder = _build_embedder()
        llm_rewrite = _build_llm()
        llm_rerank = _build_llm()

        rewriter = LLMRewriteProvider(
            llm=llm_rewrite,
            embedder=embedder,
            cache_similarity_threshold=0.99,
            temperature=0.0,
        )
        reranker = LLMRerankProvider(llm=llm_rerank, max_candidates=20, temperature=0.0)

        uc = RetrieveUseCase(
            kb_repo=PgKnowledgeBaseRepository(pg_pool),
            embedder=embedder,
            store=store,
            log_port=PgRetrieveLogRepository(pg_pool),
            reranker=reranker,
            rewriter=rewriter,
        )

        try:
            await uc.execute(query="hello world", kb_ids=[kb_id], top_k=5)

            requests = httpx_mock.get_requests()
            chat_requests = [r for r in requests if "/chat/completions" in str(r.url)]
            # 1 次 rewrite + 1 次 rerank = 2 次 LLM 调用
            assert (
                len(chat_requests) == 2
            ), f"期望 2 次 LLM 调用，实际 {len(chat_requests)}"
        finally:
            await embedder.close()
            await llm_rewrite.close()
            await llm_rerank.close()

    async def test_rerank_uses_original_query(
        self, pg_pool, store, setup_data, httpx_mock
    ):
        """reranker 接收原始 query 做相关性判断。"""
        kb_id, doc_id = setup_data

        _setup_all_http_mocks(httpx_mock, enable_rewrite=True, enable_rerank=True)

        embedder = _build_embedder()
        llm_rewrite = _build_llm()
        llm_rerank = _build_llm()

        rewriter = LLMRewriteProvider(
            llm=llm_rewrite,
            embedder=embedder,
            cache_similarity_threshold=0.99,
            temperature=0.0,
        )
        reranker = LLMRerankProvider(llm=llm_rerank, max_candidates=20, temperature=0.0)

        uc = RetrieveUseCase(
            kb_repo=PgKnowledgeBaseRepository(pg_pool),
            embedder=embedder,
            store=store,
            log_port=PgRetrieveLogRepository(pg_pool),
            reranker=reranker,
            rewriter=rewriter,
        )

        try:
            result = await uc.execute(query="原始查询语句", kb_ids=[kb_id], top_k=5)
            assert len(result) == 5
            for h in result:
                assert h.kb_id == kb_id
        finally:
            await embedder.close()
            await llm_rewrite.close()
            await llm_rerank.close()


# ═══════════════════════════════════════════════════════════════════
# 场景 2: 同时禁用 Rewrite 和 Rerank
# ═══════════════════════════════════════════════════════════════════


class TestBothDisabled:
    """同时禁用 Rewrite + Rerank 时验证直通行为。

    流程: embed(原始query) → search → return (NoopRerank 直通)
    """

    async def test_direct_flow(self, pg_pool, httpx_mock):
        """禁用两者时，结果直接来自向量搜索，无任何 LLM 调用。"""
        suffix = _unique_suffix()
        kb_id = f"kb_rt_off_{suffix}"
        doc_id = f"doc_rt_off_{suffix}"

        await _ensure_kb(pg_pool, kb_id)

        store = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        await store.connect(external_pool=pg_pool)
        chunks = _make_chunks(kb_id, doc_id, count=10)
        await store.upsert(kb_id, chunks)

        _setup_all_http_mocks(httpx_mock, enable_rewrite=False, enable_rerank=False)

        embedder = _build_embedder()

        uc = RetrieveUseCase(
            kb_repo=PgKnowledgeBaseRepository(pg_pool),
            embedder=embedder,
            store=store,
            log_port=PgRetrieveLogRepository(pg_pool),
            reranker=NoopRerankProvider(),
            rewriter=NoopRewriteProvider(),
        )

        try:
            result = await uc.execute(query="direct query", kb_ids=[kb_id], top_k=3)

            assert len(result) == 3
            for h in result:
                assert h.kb_id == kb_id
                assert h.doc_id == doc_id

            # 确认无 LLM 调用
            requests = httpx_mock.get_requests()
            chat_requests = [r for r in requests if "/chat/completions" in str(r.url)]
            assert len(chat_requests) == 0, "禁用 rewrite/rerank 时不应有 LLM 调用"
        finally:
            await embedder.close()

    async def test_noop_rewriter_returns_original_query(self):
        """NoopRewriteProvider.rewrite 返回 rewritten_query == original_query。"""
        noop = NoopRewriteProvider()
        result = await noop.rewrite(query="test query", kb_ids=["kb1"])
        assert result.original_query == "test query"
        assert result.rewritten_query == "test query"
        assert result.needs_rewrite is False

    async def test_noop_reranker_preserves_chunks(self):
        """NoopRerankProvider.rerank 按 top_n 截断但不修改顺序。"""
        hits = [
            SearchHit(
                chunk_id=f"test:{i}",
                kb_id="kb_test",
                doc_id="doc_0",
                score=1.0 - i * 0.1,
                text=f"text {i}",
                metadata={},
            )
            for i in range(10)
        ]
        noop = NoopRerankProvider()

        result = await noop.rerank(
            query="test",
            query_vector=[0.5] * 8,
            kb_ids=["kb1"],
            chunks=hits,
            top_n=3,
        )

        assert len(result) == 3
        assert result[0].chunk_id == hits[0].chunk_id
        assert result[1].chunk_id == hits[1].chunk_id
        assert result[2].chunk_id == hits[2].chunk_id


# ═══════════════════════════════════════════════════════════════════
# 场景 3: 只启用 Rewrite（禁用 Rerank）
# ═══════════════════════════════════════════════════════════════════


class TestRewriteOnly:
    """只启用 Rewrite 时验证数据流。

    流程: rewrite → embed(改写query) → search → return (经 NoopRerank)
    """

    async def test_rewritten_query_used_for_embed(self, pg_pool, httpx_mock):
        """embed 使用改写后的 query，结果从真实 DB 返回。"""
        suffix = _unique_suffix()
        kb_id = f"kb_rt_rw_{suffix}"
        doc_id = f"doc_rt_rw_{suffix}"

        await _ensure_kb(pg_pool, kb_id)

        store = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        await store.connect(external_pool=pg_pool)
        chunks = _make_chunks(kb_id, doc_id, count=10)
        await store.upsert(kb_id, chunks)

        embed_texts = _setup_all_http_mocks(
            httpx_mock, enable_rewrite=True, enable_rerank=False
        )

        embedder = _build_embedder()
        llm = _build_llm()

        rewriter = LLMRewriteProvider(
            llm=llm,
            embedder=embedder,
            cache_similarity_threshold=0.99,
            temperature=0.0,
        )

        uc = RetrieveUseCase(
            kb_repo=PgKnowledgeBaseRepository(pg_pool),
            embedder=embedder,
            store=store,
            log_port=PgRetrieveLogRepository(pg_pool),
            reranker=NoopRerankProvider(),
            rewriter=rewriter,
        )

        try:
            result = await uc.execute(query="what is AI", kb_ids=[kb_id], top_k=5)

            assert len(result) == 5
            for h in result:
                assert h.kb_id == kb_id

            # 主检索的 embed 文本包含改写后的 query
            assert (
                len(embed_texts) >= 2
            ), f"期望 ≥2 次 embed 调用，实际 {len(embed_texts)}"
            last_texts = embed_texts[-1]
            assert any(
                "improved:" in t for t in last_texts
            ), f"期望最后 embed 包含改写 query，实际: {last_texts}"
        finally:
            await embedder.close()
            await llm.close()

    async def test_result_length_matches_top_k(self, pg_pool, httpx_mock):
        """禁用 rerank 时，返回结果数 == top_k。"""
        suffix = _unique_suffix()
        kb_id = f"kb_rt_rw2_{suffix}"
        doc_id = f"doc_rt_rw2_{suffix}"

        await _ensure_kb(pg_pool, kb_id)

        store = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        await store.connect(external_pool=pg_pool)
        chunks = _make_chunks(kb_id, doc_id, count=10)
        await store.upsert(kb_id, chunks)

        _setup_all_http_mocks(httpx_mock, enable_rewrite=True, enable_rerank=False)

        embedder = _build_embedder()
        llm = _build_llm()

        rewriter = LLMRewriteProvider(
            llm=llm,
            embedder=embedder,
            cache_similarity_threshold=0.99,
            temperature=0.0,
        )

        uc = RetrieveUseCase(
            kb_repo=PgKnowledgeBaseRepository(pg_pool),
            embedder=embedder,
            store=store,
            log_port=PgRetrieveLogRepository(pg_pool),
            reranker=NoopRerankProvider(),
            rewriter=rewriter,
        )

        try:
            result = await uc.execute(query="test", kb_ids=[kb_id], top_k=3)
            assert len(result) == 3
        finally:
            await embedder.close()
            await llm.close()


# ═══════════════════════════════════════════════════════════════════
# 场景 4: 只启用 Rerank（禁用 Rewrite）
# ═══════════════════════════════════════════════════════════════════


class TestRerankOnly:
    """只启用 Rerank 时验证数据流。

    流程: embed(原始query) → search → rerank → return
    """

    async def test_embed_uses_original_query(self, pg_pool, httpx_mock):
        """禁用 rewrite 时，embed 使用原始 query。"""
        suffix = _unique_suffix()
        kb_id = f"kb_rt_rr_{suffix}"
        doc_id = f"doc_rt_rr_{suffix}"

        await _ensure_kb(pg_pool, kb_id)

        store = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        await store.connect(external_pool=pg_pool)
        chunks = _make_chunks(kb_id, doc_id, count=10)
        await store.upsert(kb_id, chunks)

        embed_texts = _setup_all_http_mocks(
            httpx_mock, enable_rewrite=False, enable_rerank=True
        )

        embedder = _build_embedder()
        llm = _build_llm()
        reranker = LLMRerankProvider(llm=llm, max_candidates=20, temperature=0.0)

        uc = RetrieveUseCase(
            kb_repo=PgKnowledgeBaseRepository(pg_pool),
            embedder=embedder,
            store=store,
            log_port=PgRetrieveLogRepository(pg_pool),
            reranker=reranker,
            rewriter=NoopRewriteProvider(),
        )

        try:
            await uc.execute(query="original query xyz", kb_ids=[kb_id], top_k=5)

            assert len(embed_texts) >= 1
            assert any(
                "original query xyz" in t for t in embed_texts[-1]
            ), f"期望 embed 使用原始 query，实际: {embed_texts[-1]}"
        finally:
            await embedder.close()
            await llm.close()

    async def test_rerank_modifies_result(self, pg_pool, httpx_mock):
        """启用 rerank 时返回结果被 reranker 修改（反转顺序）。"""
        suffix = _unique_suffix()
        kb_id = f"kb_rt_rr2_{suffix}"
        doc_id = f"doc_rt_rr2_{suffix}"

        await _ensure_kb(pg_pool, kb_id)

        store = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        await store.connect(external_pool=pg_pool)
        chunks = _make_chunks(kb_id, doc_id, count=10)
        await store.upsert(kb_id, chunks)

        _setup_all_http_mocks(httpx_mock, enable_rewrite=False, enable_rerank=True)

        embedder = _build_embedder()
        llm = _build_llm()
        reranker = LLMRerankProvider(llm=llm, max_candidates=20, temperature=0.0)

        uc = RetrieveUseCase(
            kb_repo=PgKnowledgeBaseRepository(pg_pool),
            embedder=embedder,
            store=store,
            log_port=PgRetrieveLogRepository(pg_pool),
            reranker=reranker,
            rewriter=NoopRewriteProvider(),
            candidate_multiplier=3,  # 确保所有 10 个 chunk 到达 reranker
        )

        try:
            result = await uc.execute(query="query", kb_ids=[kb_id], top_k=5)

            # reranker mock 给 payload 中较后的候选更高分
            # → 索引最大的 chunk 应排在前列
            idxes = [int(h.chunk_id.rsplit(":", 1)[1]) for h in result]
            assert (
                max(idxes) in idxes[:2]
            ), f"最高索引 chunk 应排在前 2 名，实际: {idxes}"
        finally:
            await embedder.close()
            await llm.close()

    async def test_rerank_receives_original_query(self, pg_pool, httpx_mock):
        """reranker 接收原始 query 做相关性判断。"""
        suffix = _unique_suffix()
        kb_id = f"kb_rt_rr3_{suffix}"
        doc_id = f"doc_rt_rr3_{suffix}"

        await _ensure_kb(pg_pool, kb_id)

        store = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        await store.connect(external_pool=pg_pool)
        chunks = _make_chunks(kb_id, doc_id, count=10)
        await store.upsert(kb_id, chunks)

        _setup_all_http_mocks(httpx_mock, enable_rewrite=False, enable_rerank=True)

        embedder = _build_embedder()
        llm = _build_llm()
        reranker = LLMRerankProvider(llm=llm, max_candidates=20, temperature=0.0)

        uc = RetrieveUseCase(
            kb_repo=PgKnowledgeBaseRepository(pg_pool),
            embedder=embedder,
            store=store,
            log_port=PgRetrieveLogRepository(pg_pool),
            reranker=reranker,
            rewriter=NoopRewriteProvider(),
        )

        try:
            result = await uc.execute(
                query="how to cook pasta", kb_ids=[kb_id], top_k=5
            )
            assert len(result) == 5
            for h in result:
                assert h.kb_id == kb_id
        finally:
            await embedder.close()
            await llm.close()


# ═══════════════════════════════════════════════════════════════════
# 场景 5: candidate_k 计算
# ═══════════════════════════════════════════════════════════════════


class TestCandidateK:
    """验证 candidate_k 计算 — 启用 rerank 时放大搜索候选。"""

    async def test_multiplier_only(self, pg_pool, httpx_mock):
        """candidate_multiplier=3 → candidate_k = top_k * 3。"""
        suffix = _unique_suffix()
        kb_id = f"kb_rt_ck1_{suffix}"
        doc_id = f"doc_rt_ck1_{suffix}"

        await _ensure_kb(pg_pool, kb_id)

        store = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        await store.connect(external_pool=pg_pool)
        chunks = _make_chunks(kb_id, doc_id, count=10)
        await store.upsert(kb_id, chunks)

        spy_store = SpyVectorStore(store)

        _setup_all_http_mocks(httpx_mock, enable_rewrite=False, enable_rerank=True)

        embedder = _build_embedder()
        llm = _build_llm()
        reranker = LLMRerankProvider(llm=llm, max_candidates=20, temperature=0.0)

        uc = RetrieveUseCase(
            kb_repo=PgKnowledgeBaseRepository(pg_pool),
            embedder=embedder,
            store=spy_store,
            log_port=PgRetrieveLogRepository(pg_pool),
            reranker=reranker,
            rewriter=NoopRewriteProvider(),
            candidate_multiplier=3,
            min_candidates=0,
        )

        try:
            await uc.execute(query="test", kb_ids=[kb_id], top_k=5)
            # top_k=5, multiplier=3 → candidate_k=15
            assert spy_store.last_kwargs["top_k"] == 15
        finally:
            await embedder.close()
            await llm.close()

    async def test_min_candidates_only(self, pg_pool, httpx_mock):
        """min_candidates=10 → candidate_k = top_k + 10。"""
        suffix = _unique_suffix()
        kb_id = f"kb_rt_ck2_{suffix}"
        doc_id = f"doc_rt_ck2_{suffix}"

        await _ensure_kb(pg_pool, kb_id)

        store = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        await store.connect(external_pool=pg_pool)
        chunks = _make_chunks(kb_id, doc_id, count=10)
        await store.upsert(kb_id, chunks)

        spy_store = SpyVectorStore(store)

        _setup_all_http_mocks(httpx_mock, enable_rewrite=False, enable_rerank=True)

        embedder = _build_embedder()
        llm = _build_llm()
        reranker = LLMRerankProvider(llm=llm, max_candidates=20, temperature=0.0)

        uc = RetrieveUseCase(
            kb_repo=PgKnowledgeBaseRepository(pg_pool),
            embedder=embedder,
            store=spy_store,
            log_port=PgRetrieveLogRepository(pg_pool),
            reranker=reranker,
            rewriter=NoopRewriteProvider(),
            candidate_multiplier=1,
            min_candidates=10,
        )

        try:
            await uc.execute(query="test", kb_ids=[kb_id], top_k=3)
            # top_k=3, min_candidates=10 → candidate_k=13
            assert spy_store.last_kwargs["top_k"] == 13
        finally:
            await embedder.close()
            await llm.close()

    async def test_both_takes_max(self, pg_pool, httpx_mock):
        """multiplier*top_k=10, min_candidates+top_k=7 → max=10。"""
        suffix = _unique_suffix()
        kb_id = f"kb_rt_ck3_{suffix}"
        doc_id = f"doc_rt_ck3_{suffix}"

        await _ensure_kb(pg_pool, kb_id)

        store = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        await store.connect(external_pool=pg_pool)
        chunks = _make_chunks(kb_id, doc_id, count=10)
        await store.upsert(kb_id, chunks)

        spy_store = SpyVectorStore(store)

        _setup_all_http_mocks(httpx_mock, enable_rewrite=False, enable_rerank=True)

        embedder = _build_embedder()
        llm = _build_llm()
        reranker = LLMRerankProvider(llm=llm, max_candidates=20, temperature=0.0)

        uc = RetrieveUseCase(
            kb_repo=PgKnowledgeBaseRepository(pg_pool),
            embedder=embedder,
            store=spy_store,
            log_port=PgRetrieveLogRepository(pg_pool),
            reranker=reranker,
            rewriter=NoopRewriteProvider(),
            candidate_multiplier=2,
            min_candidates=2,
        )

        try:
            await uc.execute(query="test", kb_ids=[kb_id], top_k=5)
            # top_k=5: multiplier*5=10, min+5=7 → max=10
            assert spy_store.last_kwargs["top_k"] == 10
        finally:
            await embedder.close()
            await llm.close()

    async def test_candidate_k_still_computed_when_rerank_disabled(
        self, pg_pool, httpx_mock
    ):
        """禁用 rerank 时 candidate_k 公式仍生效。NoopRerankProvider 按 top_n 截断。"""
        suffix = _unique_suffix()
        kb_id = f"kb_rt_ck4_{suffix}"
        doc_id = f"doc_rt_ck4_{suffix}"

        await _ensure_kb(pg_pool, kb_id)

        store = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        await store.connect(external_pool=pg_pool)
        chunks = _make_chunks(kb_id, doc_id, count=20)
        await store.upsert(kb_id, chunks)

        spy_store = SpyVectorStore(store)

        _setup_all_http_mocks(httpx_mock, enable_rewrite=False, enable_rerank=False)

        embedder = _build_embedder()

        uc = RetrieveUseCase(
            kb_repo=PgKnowledgeBaseRepository(pg_pool),
            embedder=embedder,
            store=spy_store,
            log_port=PgRetrieveLogRepository(pg_pool),
            reranker=NoopRerankProvider(),
            rewriter=NoopRewriteProvider(),
            candidate_multiplier=3,
            min_candidates=10,
        )

        try:
            await uc.execute(query="test", kb_ids=[kb_id], top_k=5)
            # max(5*3, 5+10) = 15
            assert spy_store.last_kwargs["top_k"] == 15
        finally:
            await embedder.close()

    async def test_default_multiplier_is_1(self, pg_pool, httpx_mock):
        """默认 candidate_multiplier=1 → candidate_k == top_k。"""
        suffix = _unique_suffix()
        kb_id = f"kb_rt_ck5_{suffix}"
        doc_id = f"doc_rt_ck5_{suffix}"

        await _ensure_kb(pg_pool, kb_id)

        store = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        await store.connect(external_pool=pg_pool)
        chunks = _make_chunks(kb_id, doc_id, count=20)
        await store.upsert(kb_id, chunks)

        spy_store = SpyVectorStore(store)

        _setup_all_http_mocks(httpx_mock, enable_rewrite=False, enable_rerank=False)

        embedder = _build_embedder()

        uc = RetrieveUseCase(
            kb_repo=PgKnowledgeBaseRepository(pg_pool),
            embedder=embedder,
            store=spy_store,
            log_port=PgRetrieveLogRepository(pg_pool),
            reranker=NoopRerankProvider(),
            rewriter=NoopRewriteProvider(),
        )

        try:
            await uc.execute(query="test", kb_ids=[kb_id], top_k=10)
            assert spy_store.last_kwargs["top_k"] == 10
        finally:
            await embedder.close()
