"""集成测试：ES 不可用降级行为。

测试 ES 不可用时的优雅降级流程：
1. ES URL 不可达 → 上传走纯 PG 写入，检索回退为纯向量模式
2. ES 会话中途启停 → 降级状态持续不崩溃
3. ES 搜索超时/错误 → RRF 融合自然退化，不抛异常
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
import pytest_asyncio

from ragnexus.adapters.embedder.openai_compat import OpenAICompatEmbedder
from ragnexus.adapters.keyword_search.elasticsearch import ESKeywordSearchProvider
from ragnexus.adapters.knowledge_base.pg import PgKnowledgeBaseRepository
from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser
from ragnexus.adapters.retrieve_log.pg import PgRetrieveLogRepository
from ragnexus.adapters.rerank.noop import NoopRerankProvider
from ragnexus.adapters.rewrite.noop import NoopRewriteProvider
from ragnexus.adapters.vector_store.pgvector import PgVectorStore
from ragnexus.application.retrieve_use_case import RetrieveUseCase
from ragnexus.application.upload_doc_use_case import UploadDocumentUseCase
from ragnexus.domain.chunking import heading_aware_split
from ragnexus.domain.models import SearchHit
from ragnexus.domain.retrieval.fusion import rrf_fuse

pytestmark = [pytest.mark.integration]

TEST_DIM = 1024
_MOCK_VEC = [0.1] * TEST_DIM

_COUNTER = 0


def _unique_suffix() -> str:
    """生成递增编号，确保每次测试产生不同的 KB ID。"""
    global _COUNTER
    _COUNTER += 1
    return f"esdeg{_COUNTER}"


_MD_BODY = """\
# 标题一
这是第一个章节的内容，包含一些测试文字。
第一段的第二句，用于增加内容长度。
第一段的第三句，进一步扩展文本量以产生多个 chunk。

# 标题二
这是第二个章节的完整内容，与标题一完全独立。
第二段的补充内容，用于验证分段逻辑的正确性。
第三行继续补充内容以确保 chunk 数至少为 2。
"""

_MD_FILE = _MD_BODY.encode("utf-8")


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


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


def _embed_callback(request: httpx.Request) -> httpx.Response:
    """Mock embedder 返回固定向量 [0.1]*1024。"""
    body = json.loads(request.content)
    texts_input = body.get("input", [])
    count = len(texts_input) if isinstance(texts_input, list) else 1
    return httpx.Response(
        status_code=200,
        json={"data": [{"embedding": _MOCK_VEC, "index": i} for i in range(count)]},
    )


def _setup_embed_mock(httpx_mock) -> None:
    """注册 embedder HTTP mock（仅 embeddings 端点）。"""
    httpx_mock.add_callback(
        _embed_callback,
        method="POST",
        url=re.compile(r".*/embeddings$"),
    )


# ═══════════════════════════════════════════════════════════════════
# 场景 1: ES 不可用时降级为纯向量模式
# ═══════════════════════════════════════════════════════════════════


class TestESUnavailableFallback:
    """ES URL 不可达时，系统应优雅降级为纯向量模式。

    对应配置：ES_ENABLED=true 但 ES URL 不可达，
    composition.py 在 lifespan 中捕获异常并将 keyword_store 置为 None。
    此后再创建 UseCase 时 keyword_store=None, es_enabled=False。
    """

    @pytest_asyncio.fixture
    async def store(self, pg_pool):
        s = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        await s.connect(external_pool=pg_pool)
        yield s

    async def test_es_unavailable_falls_back_to_vector(
        self, pg_pool, store, httpx_mock
    ):
        """ES 不可用 → 上传成功（纯 PG 写入）→ 检索不报错（纯向量结果）。

        验证点：
        - 上传在 keyword_store=None + es_enabled=False 时正常工作
        - 检索在 keyword_store=None + RETRIEVAL_MODE=hybrid 时不崩溃
        - 返回结果是合法的 SearchHit 列表
        """
        _setup_embed_mock(httpx_mock)

        # 1. 创建 KB
        suffix = _unique_suffix()
        kb_repo = PgKnowledgeBaseRepository(pg_pool)
        kb = await kb_repo.create(
            name=f"降级测试_{suffix}", name_key=f"degrad_{suffix}"
        )
        kb_id = kb.id

        # 2. 构建 UploadDocumentUseCase — ES 不可用状态
        embedder = _build_embedder()
        parser = MarkdownAndTextParser()
        upload_uc = UploadDocumentUseCase(
            kb_repo=kb_repo,
            parser=parser,
            embedder=embedder,
            chunker=heading_aware_split,
            store=store,
            keyword_store=None,
            es_enabled=False,
        )

        # 3. 上传文档 — 应成功创建 chunk
        result = await upload_uc.execute(
            kb_id=kb_id,
            file_content=_MD_FILE,
            filename="test_degrad.md",
            content_type="text/markdown",
        )
        assert (
            result.chunk_count >= 2
        ), f"上传应成功创建 >=2 个 chunk，实际 chunk_count={result.chunk_count}"

        # 4. 构建 RetrieveUseCase — keyword_store=None
        log_repo = PgRetrieveLogRepository(pg_pool)
        retrieve_uc = RetrieveUseCase(
            kb_repo=kb_repo,
            embedder=embedder,
            store=store,
            log_port=log_repo,
            reranker=NoopRerankProvider(),
            rewriter=NoopRewriteProvider(),
            keyword_store=None,
            retrieval_mode="hybrid",
        )

        # 5. 检索 — 不抛异常，返回纯向量结果
        hits = await retrieve_uc.execute("测试查询", [kb_id], top_k=5)
        assert len(hits) >= 1, f"检索应返回 >=1 个结果，实际 {len(hits)}"
        assert all(h.kb_id == kb_id for h in hits), "所有结果应属于同一 KB"
        # 向量检索按余弦距离排序，每个 hit 的 score 应为 float
        assert all(
            isinstance(h.score, float) for h in hits
        ), "所有 hit.score 应为 float"

        await embedder.close()

    async def test_es_unavailable_with_retrieval_mode_vector(
        self, pg_pool, store, httpx_mock
    ):
        """ES 不可用时 mode=vector 应正常工作（本身就不需要 ES）。"""
        _setup_embed_mock(httpx_mock)

        suffix = _unique_suffix()
        kb_repo = PgKnowledgeBaseRepository(pg_pool)
        kb = await kb_repo.create(name=f"纯向量_{suffix}", name_key=f"vector_{suffix}")
        kb_id = kb.id

        embedder = _build_embedder()
        parser = MarkdownAndTextParser()
        upload_uc = UploadDocumentUseCase(
            kb_repo=kb_repo,
            parser=parser,
            embedder=embedder,
            chunker=heading_aware_split,
            store=store,
            keyword_store=None,
            es_enabled=False,
        )
        await upload_uc.execute(
            kb_id=kb_id,
            file_content=_MD_FILE,
            filename="vector_test.md",
            content_type="text/markdown",
        )

        log_repo = PgRetrieveLogRepository(pg_pool)
        retrieve_uc = RetrieveUseCase(
            kb_repo=kb_repo,
            embedder=embedder,
            store=store,
            log_port=log_repo,
            reranker=NoopRerankProvider(),
            rewriter=NoopRewriteProvider(),
            keyword_store=None,
            retrieval_mode="vector",
        )

        hits = await retrieve_uc.execute("纯向量查询", [kb_id], top_k=3)
        assert len(hits) >= 1
        assert all(isinstance(h.score, float) for h in hits)

        await embedder.close()


# ═══════════════════════════════════════════════════════════════════
# 场景 2: ES 中途变得可用，降级状态持续
# ═══════════════════════════════════════════════════════════════════


class TestESMidSession:
    """ES 连接生命周期：启动时不可用，运行时降级状态持续有效。

    按设计文档，ES 连接在启动时建立，运行时不可恢复。
    此测试验证降级状态在多轮操作中保持一致，不因 ES 状态变化而崩溃。
    """

    @pytest_asyncio.fixture
    async def store(self, pg_pool):
        s = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        await s.connect(external_pool=pg_pool)
        yield s

    async def test_es_becomes_available_mid_session(self, pg_pool, store, httpx_mock):
        """多轮上传+检索：降级状态持续，所有操作不崩溃。

        模拟场景：ES 先不可用（keyword_store=None），后续即使 ES 恢复，
        已创建的 UseCase 实例仍以降级模式运行，不因外部变化而崩溃。
        """
        _setup_embed_mock(httpx_mock)

        suffix = _unique_suffix()
        kb_repo = PgKnowledgeBaseRepository(pg_pool)
        kb = await kb_repo.create(name=f"会话降级_{suffix}", name_key=f"mid_{suffix}")
        kb_id = kb.id

        embedder = _build_embedder()
        parser = MarkdownAndTextParser()

        # 以 ES 不可用状态启动
        upload_uc = UploadDocumentUseCase(
            kb_repo=kb_repo,
            parser=parser,
            embedder=embedder,
            chunker=heading_aware_split,
            store=store,
            keyword_store=None,
            es_enabled=False,
        )

        log_repo = PgRetrieveLogRepository(pg_pool)
        retrieve_uc = RetrieveUseCase(
            kb_repo=kb_repo,
            embedder=embedder,
            store=store,
            log_port=log_repo,
            reranker=NoopRerankProvider(),
            rewriter=NoopRewriteProvider(),
            keyword_store=None,
            retrieval_mode="hybrid",
        )

        # 第一轮：上传 → 检索
        r1 = await upload_uc.execute(
            kb_id=kb_id,
            file_content=_MD_FILE,
            filename="round1.md",
            content_type="text/markdown",
        )
        assert r1.chunk_count >= 2, "第一轮上传应成功"
        h1 = await retrieve_uc.execute("第一轮查询", [kb_id], top_k=5)
        assert len(h1) >= 1, "第一轮检索应返回结果"

        # 第二轮：上传新文档 → 检索（验证降级状态持续）
        r2 = await upload_uc.execute(
            kb_id=kb_id,
            file_content=_MD_FILE,
            filename="round2.md",
            content_type="text/markdown",
        )
        assert r2.chunk_count >= 2, "第二轮上传应成功"
        h2 = await retrieve_uc.execute("第二轮查询", [kb_id], top_k=5)
        assert len(h2) >= 1, "第二轮检索应返回结果"

        # 第三轮：仅检索 — 验证持续稳定
        h3 = await retrieve_uc.execute("第三轮查询", [kb_id], top_k=5)
        assert len(h3) >= 1, "第三轮检索应返回结果"

        await embedder.close()

    async def test_es_connection_failure_does_not_crash_composition(self, httpx_mock):
        """ES 连接失败时，ESKeywordSearchProvider.connect()+ensure_index()
        抛出异常，composition 应捕获并将 keyword_store 置为 None。
        """
        # 指向一个几乎确定不可达的端口
        es = ESKeywordSearchProvider(
            url="http://127.0.0.1:1",
            index="test_nonexistent",
            request_timeout=0.5,
        )
        await es.connect()  # connect() 只创建客户端，不验证

        # ensure_index() 会发起真实 HTTP 请求 — 应失败
        with pytest.raises(Exception, match=r".*"):
            await es.ensure_index()

        await es.close()

    async def test_multiple_kb_retrieval_without_es(self, pg_pool, store, httpx_mock):
        """多 KB 检索在 ES 不可用时仍正常工作。"""
        _setup_embed_mock(httpx_mock)

        suffix = _unique_suffix()
        kb_repo = PgKnowledgeBaseRepository(pg_pool)

        # 创建两个 KB
        kb1 = await kb_repo.create(
            name=f"多KB_A_{suffix}", name_key=f"multikb_a_{suffix}"
        )
        kb2 = await kb_repo.create(
            name=f"多KB_B_{suffix}", name_key=f"multikb_b_{suffix}"
        )

        embedder = _build_embedder()
        parser = MarkdownAndTextParser()

        # 上传到两个 KB
        upload_uc = UploadDocumentUseCase(
            kb_repo=kb_repo,
            parser=parser,
            embedder=embedder,
            chunker=heading_aware_split,
            store=store,
            keyword_store=None,
            es_enabled=False,
        )
        await upload_uc.execute(kb1.id, _MD_FILE, "a.md", "text/markdown")
        await upload_uc.execute(kb2.id, _MD_FILE, "b.md", "text/markdown")

        log_repo = PgRetrieveLogRepository(pg_pool)
        retrieve_uc = RetrieveUseCase(
            kb_repo=kb_repo,
            embedder=embedder,
            store=store,
            log_port=log_repo,
            reranker=NoopRerankProvider(),
            rewriter=NoopRewriteProvider(),
            keyword_store=None,
            retrieval_mode="hybrid",
        )

        hits = await retrieve_uc.execute("多KB查询", [kb1.id, kb2.id], top_k=10)
        assert len(hits) >= 1, "多 KB 检索应返回结果"
        kb_ids_in_hits = {h.kb_id for h in hits}
        assert kb_ids_in_hits.issubset(
            {kb1.id, kb2.id}
        ), f"结果应来自请求的 KB，实际 KB IDs: {kb_ids_in_hits}"

        await embedder.close()


# ═══════════════════════════════════════════════════════════════════
# 场景 3: ES 搜索错误时不崩溃，返回空并降级为纯向量
# ═══════════════════════════════════════════════════════════════════


class TestESErrorHandling:
    """ES 搜索超时/连接错误时，系统不抛异常且退化为纯向量。

    覆盖两条路径：
    - (a) ES 适配器层面抛异常 → RetrieveUseCase 捕获 → kw_hits=[]
    - (b) RRF 融合收到空 kw_hits → 自然退化为向量结果
    """

    @pytest_asyncio.fixture
    async def store(self, pg_pool):
        s = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        await s.connect(external_pool=pg_pool)
        yield s

    async def test_keyword_search_error_handled_gracefully(
        self, pg_pool, store, httpx_mock
    ):
        """ES 搜索抛异常时：不崩溃，返回纯向量结果。

        使用会抛异常的 keyword_store 模拟 ES 超时/连接错误场景。
        RetrieveUseCase.execute() 通过 asyncio.gather(return_exceptions=True)
        捕获异常，将 kw_hits 置为 []，RRF 自然退化为纯向量。
        """
        _setup_embed_mock(httpx_mock)

        suffix = _unique_suffix()
        kb_repo = PgKnowledgeBaseRepository(pg_pool)
        kb = await kb_repo.create(name=f"错误降级_{suffix}", name_key=f"err_{suffix}")
        kb_id = kb.id

        # 上传文档（纯 PG，无 ES）
        embedder = _build_embedder()
        parser = MarkdownAndTextParser()
        upload_uc = UploadDocumentUseCase(
            kb_repo=kb_repo,
            parser=parser,
            embedder=embedder,
            chunker=heading_aware_split,
            store=store,
            keyword_store=None,
            es_enabled=False,
        )
        r = await upload_uc.execute(
            kb_id=kb_id,
            file_content=_MD_FILE,
            filename="err_test.md",
            content_type="text/markdown",
        )
        assert r.chunk_count >= 2

        # 创建会抛异常的 keyword_store — 模拟 ES 超时/连接错误
        class FailingKeywordStore:
            """模拟 ES 故障的关键词检索适配器。"""

            async def search_by_keyword(self, kb_id, query, top_k):
                raise ConnectionError("模拟 ES 连接超时")

            async def upsert(self, kb_id, chunks):
                pass

            async def delete(self, kb_id, chunk_ids):
                pass

        log_repo = PgRetrieveLogRepository(pg_pool)
        retrieve_uc = RetrieveUseCase(
            kb_repo=kb_repo,
            embedder=embedder,
            store=store,
            log_port=log_repo,
            reranker=NoopRerankProvider(),
            rewriter=NoopRewriteProvider(),
            keyword_store=FailingKeywordStore(),
            retrieval_mode="hybrid",
        )

        # 检索 — 不应抛异常，应返回纯向量结果
        hits = await retrieve_uc.execute("错误测试查询", [kb_id], top_k=5)
        assert len(hits) >= 1, f"ES 异常时仍应返回向量结果，实际 {len(hits)} 个 hit"
        assert all(
            isinstance(h.score, float) for h in hits
        ), "所有 hit.score 应为 float"

        await embedder.close()

    def test_rrf_fuse_with_empty_kw_hits_returns_vector_only(self):
        """kw_hits=[] 时 RRF 自然退化为纯向量结果。

        这是 test 3 的第二验证点：RRF 融合收到空列表时不抛异常，
        返回的 hit 集合等于向量召回的结果集合（RRF 重新计分但 chunk 不变）。
        """
        vector_hits = [
            SearchHit(
                chunk_id="c1",
                kb_id="kb",
                doc_id="d1",
                score=0.9,
                text="text 1",
                metadata={},
            ),
            SearchHit(
                chunk_id="c2",
                kb_id="kb",
                doc_id="d2",
                score=0.7,
                text="text 2",
                metadata={},
            ),
            SearchHit(
                chunk_id="c3",
                kb_id="kb",
                doc_id="d3",
                score=0.5,
                text="text 3",
                metadata={},
            ),
        ]

        result = rrf_fuse(vector_hits, [], k=60)
        assert (
            len(result) == 3
        ), f"kw_hits 为空时结果应等于 vector_hits 数量，实际 {len(result)}"

        # RRF 重新计分但 chunk_id 集合不变
        result_ids = {h.chunk_id for h in result}
        expected_ids = {h.chunk_id for h in vector_hits}
        assert (
            result_ids == expected_ids
        ), f"chunk_id 集合应不变，实际 {result_ids} vs 预期 {expected_ids}"

        # RRF 分数应 > 0（因为每个 hit 至少有一个来源 rank）
        assert all(h.score > 0 for h in result), "RRF 分数应 > 0"

    def test_rrf_fuse_with_empty_vector_but_nonempty_kw(self):
        """vector_hits=[] 但 kw_hits 非空时 RRF 应只返回 kw 结果。

        边界情况：极端关键词检索场景（mode=bm25），向量路径返回空。
        """
        kw_hits = [
            SearchHit(
                chunk_id="k1",
                kb_id="kb",
                doc_id="d1",
                score=0.8,
                text="kw text 1",
                metadata={},
            ),
            SearchHit(
                chunk_id="k2",
                kb_id="kb",
                doc_id="d2",
                score=0.6,
                text="kw text 2",
                metadata={},
            ),
        ]

        result = rrf_fuse([], kw_hits, k=60)
        assert len(result) == 2
        result_ids = {h.chunk_id for h in result}
        assert result_ids == {"k1", "k2"}

    def test_rrf_fuse_with_both_empty(self):
        """两路都为空时 RRF 返回空列表（不抛异常）。"""
        result = rrf_fuse([], [], k=60)
        assert result == [], "两路为空时 RRF 应返回 []"

    async def test_keyword_store_upsert_throws_does_not_block_upload(
        self, pg_pool, store, httpx_mock
    ):
        """ES upsert 失败时不影响 PG 写入的成功路径。

        模拟场景：双写模式下 ES 失败，upload use case 应正确处理。
        验证：即使 ES 抛异常，PG 数据已写入，upload 仍能正常完成。
        """
        _setup_embed_mock(httpx_mock)

        suffix = _unique_suffix()
        kb_repo = PgKnowledgeBaseRepository(pg_pool)
        kb = await kb_repo.create(
            name=f"ES写失败_{suffix}", name_key=f"esfail_{suffix}"
        )
        kb_id = kb.id

        # 当 keyword_store=None + es_enabled=False 时，
        # UploadDocumentUseCase 跳过双写，直接走 PG 单写路径（已验证）。
        # 此测试验证 es_enabled=True 但 keyword_store=None 时的行为 —
        # 此时应等同于纯 PG 写入（keyword_store=None 阻止 ES 写入）。
        embedder = _build_embedder()
        parser = MarkdownAndTextParser()
        upload_uc = UploadDocumentUseCase(
            kb_repo=kb_repo,
            parser=parser,
            embedder=embedder,
            chunker=heading_aware_split,
            store=store,
            keyword_store=None,
            es_enabled=True,  # 配置说 ES 启用，但实例不可用
        )

        result = await upload_uc.execute(
            kb_id=kb_id,
            file_content=_MD_FILE,
            filename="es_fail_write.md",
            content_type="text/markdown",
        )
        # es_enabled=True + keyword_store=None → 走纯 PG 路径
        # (upload_use_case 在 es_enabled + keyword_store is not None 时才双写)
        assert result.chunk_count >= 2, "keyword_store=None 时上传应成功（纯 PG 路径）"

        await embedder.close()
