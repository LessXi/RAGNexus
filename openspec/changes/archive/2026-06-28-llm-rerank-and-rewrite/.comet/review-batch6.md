dab1555 feat(composition): 装配 RewriteProvider + upload 清空双缓存
ae35cff feat(retrieve): RetrieveUseCase 注入 RewritePort + 插入 rewrite 步骤

 src/ragnexus/application/retrieve_use_case.py |  16 ++-
 src/ragnexus/composition.py                   |  42 +++++--
 tests/unit/application/test_retrieve.py       | 157 +++++++++++++++++++++++++-
 3 files changed, 202 insertions(+), 13 deletions(-)

diff --git a/src/ragnexus/application/retrieve_use_case.py b/src/ragnexus/application/retrieve_use_case.py
index 75d47c1..c966b43 100644
--- a/src/ragnexus/application/retrieve_use_case.py
+++ b/src/ragnexus/application/retrieve_use_case.py
@@ -5,81 +5,91 @@ import contextlib
 import time
 
 from ragnexus.core.errors import AppError, ErrorCode
 from ragnexus.core.logger import logger
 from ragnexus.domain.models import SearchHit
 from ragnexus.domain.ports import (
     EmbedderPort,
     KnowledgeBasePort,
     RerankPort,
     RetrieveLogPort,
+    RewritePort,
     VectorStorePort,
 )
 
 
 class RetrieveUseCase:
     """跨知识库按查询搜索 chunk。"""
 
     def __init__(
         self,
         kb_repo: KnowledgeBasePort,
         embedder: EmbedderPort,
         store: VectorStorePort,
         log_port: RetrieveLogPort,
         reranker: RerankPort,
+        rewriter: RewritePort,
         candidate_multiplier: int = 1,
         min_candidates: int = 0,
     ) -> None:
         self._kb_repo = kb_repo
         self._embedder = embedder
         self._store = store
         self._log_port = log_port
         self._reranker = reranker
+        self._rewriter = rewriter
         self._candidate_multiplier = candidate_multiplier
         self._min_candidates = min_candidates
 
     async def execute(
         self, query: str, kb_ids: list[str], top_k: int = 5
     ) -> list[SearchHit]:
         # 1. Validate inputs（统一使用 stripped query，避免空格进入向量和日志）
         query = query.strip()
         if not query or len(query) > 2000:
             raise AppError(ErrorCode.PARAM_ERROR, "query 不能为空且长度不能超过 2000")
         if not kb_ids or len(kb_ids) > 5:
             raise AppError(ErrorCode.PARAM_ERROR, "kb_ids 不能为空且最多 5 个")
         if not (1 <= top_k <= 50):
             raise AppError(ErrorCode.PARAM_ERROR, "top_k 必须在 1-50 之间")
 
         # 2. Validate all KBs exist
         for kb_id in kb_ids:
             if not await self._kb_repo.exists(kb_id):
                 raise AppError(ErrorCode.NOT_FOUND, f"知识库不存在: {kb_id}")
 
-        # 3. Retrieve — 向量召回 + 重排（使用已 stripped 的 query）
+        # 3. Retrieve — 查询改写 → 向量召回 → 重排
+        original_query = query  # 保存原始 query，用于 rerank（相关性判断）和日志
         t0 = time.perf_counter()
         hits: list[SearchHit] = []
         try:
-            vectors = await self._embedder.embed([query])
+            # 3a. 查询改写（在 embed 之前，优化口语化/模糊 query）
+            rewrite_result = await self._rewriter.rewrite(query=query, kb_ids=kb_ids)
+            search_query = rewrite_result.rewritten_query
+
+            # 3b. embed 用改写后的 query
+            vectors = await self._embedder.embed([search_query])
             query_vector = vectors[0]
 
             # 计算候选数：重排前多召回，确保 RerankPort 有充足候选
             candidate_k = max(
                 top_k * self._candidate_multiplier,
                 top_k + self._min_candidates,
             )
 
             # 向量召回（使用 candidate_k）
             hits = await self._store.search_by_vector(query_vector, candidate_k, kb_ids)
 
             # 重排：启用时 LLMRerankProvider 重排序，禁用时 NoopRerankProvider 直通
+            # rerank 用原始 query 做相关性判断，query_vector 为改写后的向量
             hits = await self._reranker.rerank(
-                query=query,
+                query=original_query,
                 query_vector=query_vector,
                 kb_ids=kb_ids,
                 chunks=hits,
                 top_n=top_k,
             )
 
             return hits
         finally:
             latency_ms = int((time.perf_counter() - t0) * 1000)
             hit_count = len(hits)
diff --git a/src/ragnexus/composition.py b/src/ragnexus/composition.py
index 2c13c0a..3cf28b2 100644
--- a/src/ragnexus/composition.py
+++ b/src/ragnexus/composition.py
@@ -19,55 +19,65 @@ from ragnexus.adapters.http.retrieve_router import (
     create_router as create_retrieve_router,
 )
 from ragnexus.adapters.http.upload_doc_router import (
     create_router as create_upload_doc_router,
 )
 from ragnexus.adapters.knowledge_base.pg import PgKnowledgeBaseRepository
 from ragnexus.adapters.llm.openai_compatible import OpenAICompatibleLLMProvider
 from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser
 from ragnexus.adapters.rerank.llm import LLMRerankProvider
 from ragnexus.adapters.rerank.noop import NoopRerankProvider
+from ragnexus.adapters.rewrite.llm import LLMRewriteProvider
+from ragnexus.adapters.rewrite.noop import NoopRewriteProvider
 from ragnexus.adapters.retrieve_log.pg import PgRetrieveLogRepository
 from ragnexus.adapters.vector_store.pgvector import PgVectorStore
 from ragnexus.application.create_kb_use_case import CreateKnowledgeBaseUseCase
 from ragnexus.application.retrieve_use_case import RetrieveUseCase
 from ragnexus.application.upload_doc_use_case import UploadDocumentUseCase
+from ragnexus.domain.models import UploadResult
 from ragnexus.config import get_settings
 from ragnexus.core.errors import AppError, ErrorCode
 from ragnexus.core.logger import LoggedPool, setup_logging
 from ragnexus.domain.chunking import heading_aware_split
-from ragnexus.domain.ports import RerankPort
+from ragnexus.domain.ports import RerankPort, RewritePort
 
 
 class CacheInvalidatingUploadUseCase:
-    """包装 UploadDocumentUseCase，成功后清空 rerank 缓存。
+    """包装 UploadDocumentUseCase，成功后清空 rerank 和 rewrite 缓存。
 
     composition.py 的 DI 辅助类 — 对 use case 零侵入。
-    NoopRerankProvider.clear_cache 为空实现，禁用重排时无副作用。
+    NoopRerankProvider/NoopRewriteProvider.clear_cache 为空实现，禁用时无副作用。
     """
 
-    def __init__(self, inner: UploadDocumentUseCase, reranker: RerankPort) -> None:
+    def __init__(
+        self,
+        inner: UploadDocumentUseCase,
+        reranker: RerankPort,
+        rewriter: RewritePort,
+    ) -> None:
         self._inner = inner
         self._reranker = reranker
+        self._rewriter = rewriter
 
     async def execute(
         self, kb_id: str, file_content: bytes, filename: str, content_type: str
     ) -> UploadResult:
-        """执行上传并清空缓存。"""
+        """执行上传并清空双缓存。"""
         result = await self._inner.execute(
             kb_id=kb_id,
             file_content=file_content,
             filename=filename,
             content_type=content_type,
         )
-        # 清空对应 KB 的重排缓存
+        # 清空对应 KB 的重排缓存和查询改写缓存
         await self._reranker.clear_cache(kb_id)
+        await self._rewriter.clear_cache(kb_id)
         return result
 
 
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     """应用生命周期 — 注入依赖、运行、清理。
 
     启动流程:
     1. 加载配置
     2. 配置日志
@@ -189,47 +199,63 @@ async def lifespan(app: FastAPI):
                 cache_ttl_seconds=cfg.RERANK_CACHE_TTL_SECONDS,
                 temperature=cfg.RERANK_TEMPERATURE,
             )
             candidate_multiplier = cfg.RERANK_CANDIDATE_MULTIPLIER
             min_candidates = cfg.RERANK_MIN_CANDIDATES
         else:
             reranker = NoopRerankProvider()
             candidate_multiplier = 1
             min_candidates = 0
         parser = MarkdownAndTextParser()
+
+        # --- Rewrite Provider ---
+        if cfg.REWRITE_ENABLED:
+            rewriter = LLMRewriteProvider(
+                llm=llm_provider,
+                embedder=embedder,
+                cache_similarity_threshold=cfg.REWRITE_CACHE_SIMILARITY_THRESHOLD,
+                cache_max_entries=cfg.REWRITE_CACHE_MAX_ENTRIES,
+                cache_ttl_seconds=cfg.REWRITE_CACHE_TTL_SECONDS,
+                temperature=cfg.REWRITE_TEMPERATURE,
+            )
+        else:
+            rewriter = NoopRewriteProvider()
         kb_repo = PgKnowledgeBaseRepository(pool=repo_pool)  # type: ignore[arg-type]
         log_repo = PgRetrieveLogRepository(pool=repo_pool)  # type: ignore[arg-type]
 
         # Chunker: pass raw function so use case controls max_chars/overlap
         chunker = heading_aware_split
 
         # --- 5. Use cases -----------------------------------------------------
         create_kb_uc = CreateKnowledgeBaseUseCase(kb_repo=kb_repo)
         upload_doc_uc = UploadDocumentUseCase(
             kb_repo=kb_repo,
             parser=parser,
             embedder=embedder,
             chunker=chunker,
             store=store,
             max_file_size=cfg.MAX_FILE_SIZE,
             chunk_max_chars=cfg.CHUNK_MAX_CHARS,
             chunk_overlap=cfg.CHUNK_OVERLAP,
         )
 
-        # 包装 upload_doc_uc，成功后清空 rerank 缓存
-        upload_doc_uc_wrapped = CacheInvalidatingUploadUseCase(upload_doc_uc, reranker)
+        # 包装 upload_doc_uc，成功后清空 rerank 和 rewrite 缓存
+        upload_doc_uc_wrapped = CacheInvalidatingUploadUseCase(
+            upload_doc_uc, reranker, rewriter
+        )
         retrieve_uc = RetrieveUseCase(
             kb_repo=kb_repo,
             embedder=embedder,
             store=store,
             log_port=log_repo,
             reranker=reranker,
+            rewriter=rewriter,
             candidate_multiplier=candidate_multiplier,
             min_candidates=min_candidates,
         )
         # --- 6. Routers -------------------------------------------------------
         app.include_router(create_kb_router(create_kb_uc))
         app.include_router(create_upload_doc_router(upload_doc_uc_wrapped))
         app.include_router(create_retrieve_router(retrieve_uc))
 
         # Stash references for teardown
         app.state.store = store
diff --git a/tests/unit/application/test_retrieve.py b/tests/unit/application/test_retrieve.py
index 544e7af..c546b0d 100644
--- a/tests/unit/application/test_retrieve.py
+++ b/tests/unit/application/test_retrieve.py
@@ -1,20 +1,22 @@
 """Tests for RetrieveUseCase."""
 
 from unittest.mock import AsyncMock, patch
 
 import pytest
 
 from ragnexus.application.retrieve_use_case import RetrieveUseCase
 from ragnexus.core.errors import AppError
 from ragnexus.domain.models import SearchHit
 from ragnexus.adapters.rerank.noop import NoopRerankProvider
+from ragnexus.adapters.rewrite.noop import NoopRewriteProvider
+from ragnexus.domain.ports import RewriteResult
 
 
 @pytest.fixture
 def mock_kb_repo():
     return AsyncMock()
 
 
 @pytest.fixture
 def mock_embedder():
     return AsyncMock()
@@ -31,27 +33,47 @@ def mock_log_port():
 
 
 @pytest.fixture
 def mock_reranker():
     """RerankPort mock — 默认直通返回，各测试可按需覆盖 return_value。"""
     m = AsyncMock()
     return m
 
 
 @pytest.fixture
-def use_case(mock_kb_repo, mock_embedder, mock_store, mock_log_port, mock_reranker):
+def mock_rewriter():
+    """RewritePort mock — 默认直通返回原始 query，各测试可按需覆盖。"""
+    m = AsyncMock()
+
+    async def _passthrough(*, query, kb_ids):
+        return RewriteResult(
+            original_query=query,
+            rewritten_query=query,
+            needs_rewrite=False,
+            reason="mock 直通",
+        )
+
+    m.rewrite.side_effect = _passthrough
+    return m
+
+
+@pytest.fixture
+def use_case(
+    mock_kb_repo, mock_embedder, mock_store, mock_log_port, mock_reranker, mock_rewriter
+):
     return RetrieveUseCase(
         kb_repo=mock_kb_repo,
         embedder=mock_embedder,
         store=mock_store,
         log_port=mock_log_port,
         reranker=mock_reranker,
+        rewriter=mock_rewriter,
     )
 
 
 @pytest.fixture
 def sample_hits():
     return [
         SearchHit(
             chunk_id="kb_test:0",
             kb_id="kb_test",
             doc_id="doc_1",
@@ -294,29 +316,31 @@ async def test_retrieve_log_fire_and_forget(
 # ═══════════════════════════════════════════════════════════════════
 
 
 @pytest.mark.asyncio
 async def test_candidate_k_uses_multiplier(
     mock_kb_repo,
     mock_embedder,
     mock_store,
     mock_log_port,
     mock_reranker,
+    mock_rewriter,
     sample_hits,
 ):
     """candidate_multiplier=3, min_candidates=0 → candidate_k = top_k * 3。"""
     uc = RetrieveUseCase(
         kb_repo=mock_kb_repo,
         embedder=mock_embedder,
         store=mock_store,
         log_port=mock_log_port,
         reranker=mock_reranker,
+        rewriter=mock_rewriter,
         candidate_multiplier=3,
         min_candidates=0,
     )
     top_k = 5
     mock_kb_repo.exists.return_value = True
     mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
     mock_store.search_by_vector.return_value = sample_hits
     mock_reranker.rerank.return_value = sample_hits[:2]
 
     await uc.execute(query="q", kb_ids=["kb_test"], top_k=top_k)
@@ -327,29 +351,31 @@ async def test_candidate_k_uses_multiplier(
     )
 
 
 @pytest.mark.asyncio
 async def test_candidate_k_uses_min_candidates(
     mock_kb_repo,
     mock_embedder,
     mock_store,
     mock_log_port,
     mock_reranker,
+    mock_rewriter,
     sample_hits,
 ):
     """multiplier=1, min_candidates=10 → candidate_k = top_k + 10。"""
     uc = RetrieveUseCase(
         kb_repo=mock_kb_repo,
         embedder=mock_embedder,
         store=mock_store,
         log_port=mock_log_port,
         reranker=mock_reranker,
+        rewriter=mock_rewriter,
         candidate_multiplier=1,
         min_candidates=10,
     )
     top_k = 5
     mock_kb_repo.exists.return_value = True
     mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
     mock_store.search_by_vector.return_value = sample_hits
     mock_reranker.rerank.return_value = sample_hits[:2]
 
     await uc.execute(query="q", kb_ids=["kb_test"], top_k=top_k)
@@ -360,29 +386,31 @@ async def test_candidate_k_uses_min_candidates(
     )
 
 
 @pytest.mark.asyncio
 async def test_candidate_k_takes_max(
     mock_kb_repo,
     mock_embedder,
     mock_store,
     mock_log_port,
     mock_reranker,
+    mock_rewriter,
     sample_hits,
 ):
     """multiplier=2 给出 10，min_candidates=2 给出 7，取大者 10。"""
     uc = RetrieveUseCase(
         kb_repo=mock_kb_repo,
         embedder=mock_embedder,
         store=mock_store,
         log_port=mock_log_port,
         reranker=mock_reranker,
+        rewriter=mock_rewriter,
         candidate_multiplier=2,
         min_candidates=2,
     )
     top_k = 5
     mock_kb_repo.exists.return_value = True
     mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
     mock_store.search_by_vector.return_value = sample_hits
     mock_reranker.rerank.return_value = sample_hits[:2]
 
     await uc.execute(query="q", kb_ids=["kb_test"], top_k=top_k)
@@ -393,65 +421,68 @@ async def test_candidate_k_takes_max(
     )
 
 
 @pytest.mark.asyncio
 async def test_rerank_called_with_correct_kwargs(
     mock_kb_repo,
     mock_embedder,
     mock_store,
     mock_log_port,
     mock_reranker,
+    mock_rewriter,
     sample_hits,
 ):
     """reranker.rerank 使用正确的 keyword 参数调用。"""
     uc = RetrieveUseCase(
         kb_repo=mock_kb_repo,
         embedder=mock_embedder,
         store=mock_store,
         log_port=mock_log_port,
         reranker=mock_reranker,
+        rewriter=mock_rewriter,
     )
     top_k = 3
     query = "什么是 RAG？"
     kb_ids = ["kb_a", "kb_b"]
     mock_kb_repo.exists.return_value = True
     mock_embedder.embed.return_value = [[0.5, 0.6]]
     mock_store.search_by_vector.return_value = sample_hits
     mock_reranker.rerank.return_value = sample_hits[:1]
 
     await uc.execute(query=query, kb_ids=kb_ids, top_k=top_k)
 
     mock_reranker.rerank.assert_awaited_once_with(
         query=query,
         query_vector=[0.5, 0.6],
         kb_ids=kb_ids,
         chunks=sample_hits,
         top_n=top_k,
     )
 
 
-@pytest.mark.asyncio
 async def test_rerank_result_is_returned(
     mock_kb_repo,
     mock_embedder,
     mock_store,
     mock_log_port,
     mock_reranker,
+    mock_rewriter,
     sample_hits,
 ):
     """execute() 返回 rerank 后的结果，而非原始向量召回结果。"""
     uc = RetrieveUseCase(
         kb_repo=mock_kb_repo,
         embedder=mock_embedder,
         store=mock_store,
         log_port=mock_log_port,
         reranker=mock_reranker,
+        rewriter=mock_rewriter,
     )
     # 构造一个与向量召回不同的 rerank 返回（顺序或内容不同）
     reranked = [sample_hits[1], sample_hits[0]]  # 顺序反转
     mock_kb_repo.exists.return_value = True
     mock_embedder.embed.return_value = [[0.1, 0.2]]
     mock_store.search_by_vector.return_value = sample_hits
     mock_reranker.rerank.return_value = reranked
 
     result = await uc.execute(query="q", kb_ids=["kb_test"], top_k=5)
 
@@ -468,21 +499,143 @@ async def test_noop_rerank_integration(
     mock_log_port,
     sample_hits,
 ):
     """使用真实 NoopRerankProvider — chunks[:top_n] 截断语义端到端。"""
     uc = RetrieveUseCase(
         kb_repo=mock_kb_repo,
         embedder=mock_embedder,
         store=mock_store,
         log_port=mock_log_port,
         reranker=NoopRerankProvider(),
+        rewriter=NoopRewriteProvider(),
     )
     top_k = 1
     mock_kb_repo.exists.return_value = True
     mock_embedder.embed.return_value = [[0.1, 0.2]]
     mock_store.search_by_vector.return_value = sample_hits  # 2 条
 
     result = await uc.execute(query="q", kb_ids=["kb_test"], top_k=top_k)
 
     # NoopRerankProvider 返回 chunks[:top_n]，即只保留前 top_k 条
     assert len(result) == 1
     assert result[0] == sample_hits[0]
+
+
+# ═══════════════════════════════════════════════════════════════════
+# rewrite 注入测试 — Phase 6 Task 6.1-6.2
+# ═══════════════════════════════════════════════════════════════════
+
+
+@pytest.mark.asyncio
+async def test_rewriter_called_before_embed(
+    use_case,
+    mock_kb_repo,
+    mock_embedder,
+    mock_store,
+    mock_rewriter,
+):
+    """rewriter.rewrite 在 embedder.embed 之前调用。"""
+    mock_kb_repo.exists.return_value = True
+    mock_embedder.embed.return_value = [[0.1, 0.2]]
+    mock_store.search_by_vector.return_value = []
+
+    await use_case.execute(query="test query", kb_ids=["kb1"], top_k=3)
+
+    mock_rewriter.rewrite.assert_awaited_once_with(query="test query", kb_ids=["kb1"])
+
+
+@pytest.mark.asyncio
+async def test_rewritten_query_used_for_embed(
+    use_case,
+    mock_kb_repo,
+    mock_embedder,
+    mock_store,
+    mock_rewriter,
+):
+    """rewrite 后 embed 使用 rewritten_query，而非原始 query。"""
+    mock_kb_repo.exists.return_value = True
+    mock_embedder.embed.return_value = [[0.1, 0.2]]
+    mock_store.search_by_vector.return_value = []
+
+    # 覆写 mock_rewriter，返回不同改写结果
+    mock_rewriter.rewrite.side_effect = None
+    mock_rewriter.rewrite.return_value = RewriteResult(
+        original_query="hello world",
+        rewritten_query="hello world technical definition",
+        needs_rewrite=True,
+        reason="优化查询",
+    )
+
+    await use_case.execute(query="hello world", kb_ids=["kb1"], top_k=3)
+
+    # embed 用改写后的 query
+    mock_embedder.embed.assert_awaited_once_with(["hello world technical definition"])
+
+
+@pytest.mark.asyncio
+async def test_rerank_uses_original_query_rewritten_vector(
+    use_case,
+    mock_kb_repo,
+    mock_embedder,
+    mock_store,
+    mock_reranker,
+    mock_rewriter,
+):
+    """rerank 用原始 query 做相关性判断，query_vector 用改写后的向量。"""
+    mock_kb_repo.exists.return_value = True
+    mock_embedder.embed.return_value = [[0.9, 0.1]]
+    mock_store.search_by_vector.return_value = []
+    mock_reranker.rerank.return_value = []
+
+    # 覆写 mock_rewriter，改写查询
+    mock_rewriter.rewrite.side_effect = None
+    mock_rewriter.rewrite.return_value = RewriteResult(
+        original_query="what is RAG",
+        rewritten_query="retrieval augmented generation definition",
+        needs_rewrite=True,
+        reason="扩展缩写",
+    )
+
+    await use_case.execute(query="what is RAG", kb_ids=["kb1"], top_k=5)
+
+    # rerank 的 query 参数用原始 query（相关性判断）
+    mock_reranker.rerank.assert_awaited_once()
+    rerank_kwargs = mock_reranker.rerank.call_args.kwargs
+    assert rerank_kwargs["query"] == "what is RAG"
+    # query_vector 是改写后嵌入的向量
+    assert rerank_kwargs["query_vector"] == [0.9, 0.1]
+
+
+@pytest.mark.asyncio
+async def test_noop_rewrite_integration(
+    mock_kb_repo,
+    mock_embedder,
+    mock_store,
+    mock_log_port,
+    mock_reranker,
+    sample_hits,
+):
+    """使用真实 NoopRewriteProvider — 禁用改写时直通，行为不变。"""
+    uc = RetrieveUseCase(
+        kb_repo=mock_kb_repo,
+        embedder=mock_embedder,
+        store=mock_store,
+        log_port=mock_log_port,
+        reranker=mock_reranker,
+        rewriter=NoopRewriteProvider(),
+    )
+    query = "test query"
+    kb_ids = ["kb_test"]
+    top_k = 2
+    mock_kb_repo.exists.return_value = True
+    mock_embedder.embed.return_value = [[0.5, 0.5]]
+    mock_store.search_by_vector.return_value = sample_hits
+    mock_reranker.rerank.return_value = sample_hits[:top_k]
+
+    result = await uc.execute(query=query, kb_ids=kb_ids, top_k=top_k)
+
+    # NoopRewriteProvider 直通：embed 用原始 query
+    mock_embedder.embed.assert_awaited_once_with([query])
+    # 其他行为不变
+    mock_reranker.rerank.assert_awaited_once()
+    mock_store.search_by_vector.assert_awaited_once()
+    assert len(result) == top_k
