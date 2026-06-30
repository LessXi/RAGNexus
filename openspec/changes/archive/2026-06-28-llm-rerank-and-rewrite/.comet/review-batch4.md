4c69af7 feat(composition): 装配 LLMProvider + RerankProvider + upload 缓存清空
17986a5 feat(retrieve): RetrieveUseCase 注入 RerankPort + 插入 rerank 步骤
5067aba fix(rerank): NoopRerankProvider 按 top_n 截断

 src/ragnexus/adapters/rerank/noop.py          |   6 +-
 src/ragnexus/application/retrieve_use_case.py |  30 ++-
 src/ragnexus/composition.py                   |  69 ++++-
 tests/unit/adapters/test_middleware.py        | 368 +++++++++++++++++++++++---
 tests/unit/application/test_retrieve.py       | 284 +++++++++++++++++++-
 tests/unit/test_noop_rerank.py                |  27 +-
 6 files changed, 704 insertions(+), 80 deletions(-)

diff --git a/src/ragnexus/adapters/rerank/noop.py b/src/ragnexus/adapters/rerank/noop.py
index ef59131..e59b0ca 100644
--- a/src/ragnexus/adapters/rerank/noop.py
+++ b/src/ragnexus/adapters/rerank/noop.py
@@ -2,29 +2,29 @@
 
 禁用重排时的直通实现：rerank 返回原始 chunks，clear_cache 空实现。
 """
 
 from ragnexus.domain.models import SearchHit
 
 
 class NoopRerankProvider:
     """空重排提供者 — 禁用重排时的直通实现。
 
-    rerank 直接返回原始 chunks（不排序、不截断），
+    rerank 返回原始 chunks（不排序，按 top_n 截断），
     clear_cache 空实现（无缓存可清）。
     """
 
     async def rerank(
         self,
         *,
         query: str,
         query_vector: list[float],
         kb_ids: list[str],
         chunks: list[SearchHit],
         top_n: int,
     ) -> list[SearchHit]:
-        """直通返回原始 chunks，不做任何重排。"""
-        return chunks
+        """直通返回原始 chunks（不排序，按 top_n 截断），不做重排。"""
+        return chunks[:top_n]
 
     async def clear_cache(self, kb_id: str) -> None:
         """空实现 — 无缓存可清。"""
         pass
diff --git a/src/ragnexus/application/retrieve_use_case.py b/src/ragnexus/application/retrieve_use_case.py
index 0d90c94..75d47c1 100644
--- a/src/ragnexus/application/retrieve_use_case.py
+++ b/src/ragnexus/application/retrieve_use_case.py
@@ -3,63 +3,89 @@
 import asyncio
 import contextlib
 import time
 
 from ragnexus.core.errors import AppError, ErrorCode
 from ragnexus.core.logger import logger
 from ragnexus.domain.models import SearchHit
 from ragnexus.domain.ports import (
     EmbedderPort,
     KnowledgeBasePort,
+    RerankPort,
     RetrieveLogPort,
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
+        reranker: RerankPort,
+        candidate_multiplier: int = 1,
+        min_candidates: int = 0,
     ) -> None:
         self._kb_repo = kb_repo
         self._embedder = embedder
         self._store = store
         self._log_port = log_port
+        self._reranker = reranker
+        self._candidate_multiplier = candidate_multiplier
+        self._min_candidates = min_candidates
 
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
 
-        # 3. Retrieve（使用已 stripped 的 query）
+        # 3. Retrieve — 向量召回 + 重排（使用已 stripped 的 query）
         t0 = time.perf_counter()
         hits: list[SearchHit] = []
         try:
             vectors = await self._embedder.embed([query])
-            hits = await self._store.search_by_vector(vectors[0], top_k, kb_ids)
+            query_vector = vectors[0]
+
+            # 计算候选数：重排前多召回，确保 RerankPort 有充足候选
+            candidate_k = max(
+                top_k * self._candidate_multiplier,
+                top_k + self._min_candidates,
+            )
+
+            # 向量召回（使用 candidate_k）
+            hits = await self._store.search_by_vector(query_vector, candidate_k, kb_ids)
+
+            # 重排：启用时 LLMRerankProvider 重排序，禁用时 NoopRerankProvider 直通
+            hits = await self._reranker.rerank(
+                query=query,
+                query_vector=query_vector,
+                kb_ids=kb_ids,
+                chunks=hits,
+                top_n=top_k,
+            )
+
             return hits
         finally:
             latency_ms = int((time.perf_counter() - t0) * 1000)
             hit_count = len(hits)
             asyncio.create_task(
                 self._safe_log(query, kb_ids, top_k, hit_count, latency_ms)
             )
 
     async def _safe_log(
         self,
diff --git a/src/ragnexus/composition.py b/src/ragnexus/composition.py
index c4769bb..54e4f26 100644
--- a/src/ragnexus/composition.py
+++ b/src/ragnexus/composition.py
@@ -15,30 +15,58 @@ from ragnexus.adapters.embedder.openai_compat import OpenAICompatEmbedder
 from ragnexus.adapters.http.create_kb_router import create_router as create_kb_router
 from ragnexus.adapters.http.error_handlers import register_error_handlers
 from ragnexus.adapters.http.middleware import LoggingMiddleware
 from ragnexus.adapters.http.retrieve_router import (
     create_router as create_retrieve_router,
 )
 from ragnexus.adapters.http.upload_doc_router import (
     create_router as create_upload_doc_router,
 )
 from ragnexus.adapters.knowledge_base.pg import PgKnowledgeBaseRepository
+from ragnexus.adapters.llm.openai_compatible import OpenAICompatibleLLMProvider
 from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser
+from ragnexus.adapters.rerank.llm import LLMRerankProvider
+from ragnexus.adapters.rerank.noop import NoopRerankProvider
 from ragnexus.adapters.retrieve_log.pg import PgRetrieveLogRepository
 from ragnexus.adapters.vector_store.pgvector import PgVectorStore
 from ragnexus.application.create_kb_use_case import CreateKnowledgeBaseUseCase
 from ragnexus.application.retrieve_use_case import RetrieveUseCase
 from ragnexus.application.upload_doc_use_case import UploadDocumentUseCase
 from ragnexus.config import get_settings
 from ragnexus.core.errors import AppError, ErrorCode
 from ragnexus.core.logger import LoggedPool, setup_logging
 from ragnexus.domain.chunking import heading_aware_split
+from ragnexus.domain.ports import RerankPort
+
+
+class CacheInvalidatingUploadUseCase:
+    """包装 UploadDocumentUseCase，成功后清空 rerank 缓存。
+
+    composition.py 的 DI 辅助类 — 对 use case 零侵入。
+    NoopRerankProvider.clear_cache 为空实现，禁用重排时无副作用。
+    """
+
+    def __init__(self, inner: UploadDocumentUseCase, reranker: RerankPort) -> None:
+        self._inner = inner
+        self._reranker = reranker
+
+    async def execute(self, kb_id: str, file_content: bytes, filename: str, content_type: str):
+        """执行上传并清空缓存。"""
+        result = await self._inner.execute(
+            kb_id=kb_id,
+            file_content=file_content,
+            filename=filename,
+            content_type=content_type,
+        )
+        # 清空对应 KB 的重排缓存
+        await self._reranker.clear_cache(kb_id)
+        return result
 
 
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     """应用生命周期 — 注入依赖、运行、清理。
 
     启动流程:
     1. 加载配置
     2. 配置日志
     3. 创建并连接 PgVectorStore（创建含 pgvector 的 asyncpg 连接池）
@@ -128,55 +156,92 @@ async def lifespan(app: FastAPI):
             api_key=cfg.EMBED_API_KEY,
             model=cfg.EMBED_MODEL,
             dim=cfg.EMBED_DIM,
             batch_size=cfg.EMBED_BATCH_SIZE,
             max_concurrency=cfg.EMBED_MAX_CONCURRENCY,
             max_retries=cfg.EMBED_MAX_RETRIES,
             request_timeout=cfg.EMBED_REQUEST_TIMEOUT,
             connect_timeout=cfg.EMBED_CONNECT_TIMEOUT,
             retry_backoff_base=cfg.EMBED_RETRY_BACKOFF_BASE,
         )
+
+        # --- LLM Provider（通用大模型调用，被 rerank 共享）---
+        llm_provider = OpenAICompatibleLLMProvider(
+            base_url=cfg.LLM_BASE_URL,
+            api_key=cfg.LLM_API_KEY,
+            model=cfg.LLM_MODEL,
+            max_concurrency=cfg.LLM_MAX_CONCURRENCY,
+            max_retries=cfg.LLM_MAX_RETRIES,
+            request_timeout=cfg.LLM_REQUEST_TIMEOUT,
+            connect_timeout=cfg.LLM_CONNECT_TIMEOUT,
+            retry_backoff_base=cfg.LLM_RETRY_BACKOFF_BASE,
+        )
+
+        # --- Rerank Provider ---
+        if cfg.RERANK_ENABLED:
+            reranker = LLMRerankProvider(
+                llm=llm_provider,
+                max_candidates=cfg.RERANK_MAX_CANDIDATES,
+                chunk_max_chars=cfg.RERANK_CHUNK_MAX_CHARS,
+                cache_similarity_threshold=cfg.RERANK_CACHE_SIMILARITY_THRESHOLD,
+                cache_max_entries=cfg.RERANK_CACHE_MAX_ENTRIES,
+                cache_ttl_seconds=cfg.RERANK_CACHE_TTL_SECONDS,
+                temperature=cfg.RERANK_TEMPERATURE,
+            )
+            candidate_multiplier = cfg.RERANK_CANDIDATE_MULTIPLIER
+            min_candidates = cfg.RERANK_MIN_CANDIDATES
+        else:
+            reranker = NoopRerankProvider()
+            candidate_multiplier = 1
+            min_candidates = 0
         parser = MarkdownAndTextParser()
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
+
+        # 包装 upload_doc_uc，成功后清空 rerank 缓存
+        upload_doc_uc_wrapped = CacheInvalidatingUploadUseCase(upload_doc_uc, reranker)
         retrieve_uc = RetrieveUseCase(
             kb_repo=kb_repo,
             embedder=embedder,
             store=store,
             log_port=log_repo,
+            reranker=reranker,
+            candidate_multiplier=candidate_multiplier,
+            min_candidates=min_candidates,
         )
-
         # --- 6. Routers -------------------------------------------------------
         app.include_router(create_kb_router(create_kb_uc))
-        app.include_router(create_upload_doc_router(upload_doc_uc))
+        app.include_router(create_upload_doc_router(upload_doc_uc_wrapped))
         app.include_router(create_retrieve_router(retrieve_uc))
 
         # Stash references for teardown
         app.state.store = store
         app.state.repo_pool = repo_pool
 
+        app.state.retrieve_uc = retrieve_uc
+        app.state.upload_doc_uc = upload_doc_uc_wrapped
         yield
 
     finally:
         # 确保所有资源被清理，即使启动阶段抛出异常
         # 清理顺序：后创建的先关闭
         try:
             if _raw_repo_pool is not None:
                 await _raw_repo_pool.close()
         finally:
             try:
diff --git a/tests/unit/adapters/test_middleware.py b/tests/unit/adapters/test_middleware.py
index d81d480..44b3319 100644
--- a/tests/unit/adapters/test_middleware.py
+++ b/tests/unit/adapters/test_middleware.py
@@ -64,23 +64,21 @@ class TestLoggingMiddleware:
     使用 Starlette 最小应用 + TestClient 模拟 HTTP 请求，
     捕获 ragnexus logger 的输出来验证中间件行为。
     在 LoggingMiddleware 实现之前全部 RED。
     """
 
     @pytest.fixture
     def captured(self) -> list[logging.LogRecord]:
         return []
 
     @pytest.fixture
-    def handler(
-        self, captured: list[logging.LogRecord]
-    ) -> Generator[_ListHandler, None, None]:
+    def handler(self, captured: list[logging.LogRecord]) -> Generator[_ListHandler, None, None]:
         h = _add_capture_handler(captured)
         yield h
         _remove_capture_handler(h)
 
     @staticmethod
     def _build_app() -> Starlette:
         """构建带 LoggingMiddleware 的最小 Starlette 应用。"""
 
         async def echo_json(request):
             import json
@@ -109,104 +107,94 @@ class TestLoggingMiddleware:
     def test_adds_req_id_when_missing(
         self, captured: list[logging.LogRecord], handler: _ListHandler
     ):
         """缺少 X-Request-ID 时，中间件应自动生成 req_id。"""
         app = self._build_app()
         client = TestClient(app)
 
         resp = client.post("/echo", json={"msg": "hello"})
         assert resp.status_code == 200
 
-        req_logs = [
-            r for r in captured if getattr(r, "event_type", None) == "API_REQUEST"
-        ]
+        req_logs = [r for r in captured if getattr(r, "event_type", None) == "API_REQUEST"]
         assert len(req_logs) >= 1, "应该至少记录一条 API_REQUEST"
         req_id = getattr(req_logs[0], "req_id", None)
         assert req_id is not None, "req_id 不应为 None"
         assert len(req_id) >= 8, "req_id 至少 8 个字符"
 
     def test_preserves_existing_req_id(
         self, captured: list[logging.LogRecord], handler: _ListHandler
     ):
         """请求携带 X-Request-ID 时，中间件应保留该值。"""
         app = self._build_app()
         client = TestClient(app)
 
         resp = client.post(
             "/echo",
             json={"msg": "hello"},
             headers={"X-Request-ID": "my-custom-id"},
         )
         assert resp.status_code == 200
 
-        req_logs = [
-            r for r in captured if getattr(r, "event_type", None) == "API_REQUEST"
-        ]
+        req_logs = [r for r in captured if getattr(r, "event_type", None) == "API_REQUEST"]
         assert len(req_logs) >= 1
         assert getattr(req_logs[0], "req_id", None) == "my-custom-id"
 
     def test_logs_api_request_and_response(
         self, captured: list[logging.LogRecord], handler: _ListHandler
     ):
         """应同时记录 API_REQUEST 和 API_RESPONSE 事件。"""
         app = self._build_app()
         client = TestClient(app)
 
         resp = client.post("/echo", json={"msg": "hello"})
         assert resp.status_code == 200
 
         event_types = {getattr(r, "event_type", None) for r in captured}
         assert "API_REQUEST" in event_types, "应记录 API_REQUEST"
         assert "API_RESPONSE" in event_types, "应记录 API_RESPONSE"
 
-        resp_logs = [
-            r for r in captured if getattr(r, "event_type", None) == "API_RESPONSE"
-        ]
+        resp_logs = [r for r in captured if getattr(r, "event_type", None) == "API_RESPONSE"]
         assert len(resp_logs) >= 1
         assert getattr(resp_logs[0], "status", 0) == 200
 
     def test_reads_json_body_and_refills(
         self, captured: list[logging.LogRecord], handler: _ListHandler
     ):
         """JSON 请求体应被读取、记录并回填给下游路由。"""
         app = self._build_app()
         client = TestClient(app)
 
         resp = client.post("/echo", json={"msg": "hello"})
         assert resp.status_code == 200
         assert resp.json() == {"msg": "hello"}
 
-        req_logs = [
-            r for r in captured if getattr(r, "event_type", None) == "API_REQUEST"
-        ]
+        req_logs = [r for r in captured if getattr(r, "event_type", None) == "API_REQUEST"]
         assert len(req_logs) >= 1
         body_present = getattr(req_logs[0], "body_present", False)
         body_length = getattr(req_logs[0], "body_length", 0)
         assert body_present is True
         assert body_length > 0
 
     def test_skips_body_for_multipart(
         self, captured: list[logging.LogRecord], handler: _ListHandler
     ):
         """multipart 请求应跳过 body 读取。"""
         app = self._build_app()
         client = TestClient(app)
 
         resp = client.post(
             "/upload",
             files={"file": ("test.txt", b"hello world", "text/plain")},
         )
         assert resp.status_code == 200
 
-        req_logs = [
-            r for r in captured if getattr(r, "event_type", None) == "API_REQUEST"
-        ]
+        req_logs = [r for r in captured if getattr(r, "event_type", None) == "API_REQUEST"]
         assert len(req_logs) >= 1
         body_present = getattr(req_logs[0], "body_present", True)
         assert body_present is False, "multipart 不应读取 body"
 
     def test_clears_context_after_request(
         self, captured: list[logging.LogRecord], handler: _ListHandler
     ):
         """请求结束后 ContextVar 应被清理。"""
         from ragnexus.core.logger import _log_ctx, clear_log_context
 
@@ -239,26 +227,21 @@ class TestLogModelCallOnEmbedder:
         from ragnexus.adapters.embedder.openai_compat import OpenAICompatEmbedder
 
         def handler(request: httpx.Request) -> httpx.Response:
             import json
 
             dim = 1024
             body = json.loads(request.content)
             inputs = body["input"]
             return httpx.Response(
                 200,
-                json={
-                    "data": [
-                        {"index": i, "embedding": [0.1] * dim}
-                        for i in range(len(inputs))
-                    ]
-                },
+                json={"data": [{"index": i, "embedding": [0.1] * dim} for i in range(len(inputs))]},
             )
 
         transport = httpx.MockTransport(handler)
         client = httpx.AsyncClient(transport=transport)
 
         emb = OpenAICompatEmbedder(
             base_url="https://fake.example.com/v1",
             api_key="test-key",
             model="text-embedding-v3",
             dim=1024,
@@ -274,30 +257,28 @@ class TestLogModelCallOnEmbedder:
         """
         records: list[logging.LogRecord] = []
         handler = _add_capture_handler(records)
         try:
             emb = self._make_embedder()
             result = asyncio.run(emb.embed(["hello world"]))
             assert len(result) == 1
             assert len(result[0]) == 1024
 
             event_types = {getattr(r, "event_type", None) for r in records}
-            assert (
-                "MODEL_REQUEST" in event_types
-            ), "未检测到 MODEL_REQUEST — @log_model_call 可能尚未添加到 embed()"
-            assert (
-                "MODEL_RESPONSE" in event_types
-            ), "未检测到 MODEL_RESPONSE — @log_model_call 可能尚未添加到 embed()"
-
-            resp_logs = [
-                r for r in records if getattr(r, "event_type", None) == "MODEL_RESPONSE"
-            ]
+            assert "MODEL_REQUEST" in event_types, (
+                "未检测到 MODEL_REQUEST — @log_model_call 可能尚未添加到 embed()"
+            )
+            assert "MODEL_RESPONSE" in event_types, (
+                "未检测到 MODEL_RESPONSE — @log_model_call 可能尚未添加到 embed()"
+            )
+
+            resp_logs = [r for r in records if getattr(r, "event_type", None) == "MODEL_RESPONSE"]
             assert len(resp_logs) >= 1
             assert getattr(resp_logs[0], "model", None) == "text-embedding-v3"
         finally:
             _remove_capture_handler(handler)
 
     def test_embed_error_logs_model_response_with_error(self):
         """embed() 失败时应记录 MODEL_RESPONSE 并包含 error 字段。"""
         from ragnexus.core.errors import AppError
 
         records: list[logging.LogRecord] = []
@@ -306,26 +287,22 @@ class TestLogModelCallOnEmbedder:
             emb = self._make_embedder()
             emb._client = httpx.AsyncClient(
                 transport=httpx.MockTransport(
                     lambda _: httpx.Response(500, text="Internal Server Error")
                 )
             )
 
             with pytest.raises(AppError):
                 asyncio.run(emb.embed(["test"]))
 
-            err_logs = [
-                r for r in records if getattr(r, "event_type", None) == "MODEL_RESPONSE"
-            ]
-            assert (
-                len(err_logs) >= 1
-            ), "未检测到失败时的 MODEL_RESPONSE — @log_model_call 未生效"
+            err_logs = [r for r in records if getattr(r, "event_type", None) == "MODEL_RESPONSE"]
+            assert len(err_logs) >= 1, "未检测到失败时的 MODEL_RESPONSE — @log_model_call 未生效"
             error_val = getattr(err_logs[0], "error", None)
             assert error_val is not None
         finally:
             _remove_capture_handler(handler)
 
 
 # ============================================================================
 # TestLoggedPoolWiring — Phase 5: 数据库日志代理接入
 # ============================================================================
 
@@ -353,20 +330,23 @@ class TestLoggedPoolWiring:
             patch(
                 "ragnexus.composition.asyncpg.create_pool",
                 new_callable=AsyncMock,
             ) as mock_create_pool,
             patch(
                 "ragnexus.composition.PgVectorStore",
                 autospec=True,
             ) as mock_store_cls,
             patch("ragnexus.composition.get_settings") as mock_get_settings,
             patch("ragnexus.composition.setup_logging") as mock_setup_logging,
+            patch(
+                "ragnexus.composition.OpenAICompatibleLLMProvider",
+            ),
         ):
             # 配置 mock 返回值
             mock_pool = MagicMock()
             mock_create_pool.return_value = mock_pool
             mock_pool.close = AsyncMock()
 
             mock_store = mock_store_cls.return_value
             mock_store.connect = AsyncMock()
             mock_store.close = AsyncMock()
             mock_store.pool = MagicMock()
@@ -383,20 +363,31 @@ class TestLoggedPoolWiring:
             mock_cfg.EMBED_MODEL = "text-embedding-v3"
             mock_cfg.EMBED_BATCH_SIZE = 50
             mock_cfg.EMBED_MAX_CONCURRENCY = 5
             mock_cfg.EMBED_MAX_RETRIES = 3
             mock_cfg.EMBED_REQUEST_TIMEOUT = 30.0
             mock_cfg.EMBED_CONNECT_TIMEOUT = 5.0
             mock_cfg.EMBED_RETRY_BACKOFF_BASE = 2.0
             mock_cfg.MAX_FILE_SIZE = 10 * 1024 * 1024
             mock_cfg.CHUNK_MAX_CHARS = 1500
             mock_cfg.CHUNK_OVERLAP = 50
+            # LLM 配置（lifespan 现在会创建 LLMProvider）
+            mock_cfg.LLM_BASE_URL = "https://fake-llm.example.com"
+            mock_cfg.LLM_API_KEY = "test-llm"
+            mock_cfg.LLM_MODEL = "test-model"
+            mock_cfg.LLM_MAX_CONCURRENCY = 3
+            mock_cfg.LLM_MAX_RETRIES = 2
+            mock_cfg.LLM_REQUEST_TIMEOUT = 30.0
+            mock_cfg.LLM_CONNECT_TIMEOUT = 5.0
+            mock_cfg.LLM_RETRY_BACKOFF_BASE = 2.0
+            # 禁用重排（避免 LLMRerankProvider 构造时的副作用）
+            mock_cfg.RERANK_ENABLED = False
             mock_get_settings.return_value = mock_cfg
 
             mock_setup_logging.return_value = MagicMock()
 
             # 运行 lifespan 并检查 repo_pool 是否被包装
             async def _run_lifespan():
                 results = []
 
                 @asynccontextmanager
                 async def test_lifespan(app):
@@ -404,13 +395,304 @@ class TestLoggedPoolWiring:
                         results.append(app.state.repo_pool)
                     yield
 
                 app = FastAPI(lifespan=test_lifespan)
                 async with app.router.lifespan_context(app):
                     pass
                 return results[0] if results else None
 
             repo_pool = asyncio.run(_run_lifespan())
             assert repo_pool is not None, "lifespan 应设置 app.state.repo_pool"
-            assert isinstance(
-                repo_pool, LoggedPool
-            ), f"repo_pool 应为 LoggedPool 实例，实际类型为 {type(repo_pool).__name__}"
+            assert isinstance(repo_pool, LoggedPool), (
+                f"repo_pool 应为 LoggedPool 实例，实际类型为 {type(repo_pool).__name__}"
+            )
+
+
+# ============================================================================
+# TestRerankLLMWiring — Phase 5.5: LLM + Rerank DI 装配
+# ============================================================================
+
+
+class TestRerankLLMWiring:
+    """验证 composition.py lifespan 中 LLMProvider + RerankProvider + upload 缓存清空。
+
+    RED → 当前尚未添加 app.state.retrieve_uc / app.state.upload_doc_uc。
+    GREEN → lifespan 创建 LLMProvider + RerankProvider 并注入 use case。
+    """
+
+    def test_rerank_disabled_uses_noop_reranker(self):
+        """RERANK_ENABLED=False 时，retrieve_uc 的 reranker 为 NoopRerankProvider 实例。"""
+        from contextlib import asynccontextmanager
+
+        from fastapi import FastAPI
+
+        from ragnexus.adapters.rerank.noop import NoopRerankProvider
+        from ragnexus.composition import lifespan as real_lifespan
+
+        with (
+            patch(
+                "ragnexus.composition.asyncpg.create_pool",
+                new_callable=AsyncMock,
+            ) as mock_create_pool,
+            patch(
+                "ragnexus.composition.PgVectorStore",
+                autospec=True,
+            ) as mock_store_cls,
+            patch("ragnexus.composition.get_settings") as mock_get_settings,
+            patch("ragnexus.composition.setup_logging") as mock_setup_logging,
+            patch("ragnexus.composition.OpenAICompatibleLLMProvider"),
+        ):
+            mock_pool = MagicMock()
+            mock_create_pool.return_value = mock_pool
+            mock_pool.close = AsyncMock()
+
+            mock_store = mock_store_cls.return_value
+            mock_store.connect = AsyncMock()
+            mock_store.close = AsyncMock()
+            mock_store.pool = MagicMock()
+            mock_store.pool.fetchval = AsyncMock(return_value=1024)
+
+            mock_cfg = MagicMock()
+            mock_cfg.EMBED_DIM = 1024
+            # 确保 RERANK_ENABLED=False（默认）
+            mock_cfg.RERANK_ENABLED = False
+            # Embedder 配置
+            mock_cfg.EMBED_BASE_URL = "https://fake.example.com"
+            mock_cfg.EMBED_API_KEY = "test"
+            mock_cfg.EMBED_MODEL = "text-embedding-v3"
+            mock_cfg.EMBED_BATCH_SIZE = 50
+            mock_cfg.EMBED_MAX_CONCURRENCY = 5
+            mock_cfg.EMBED_MAX_RETRIES = 3
+            mock_cfg.EMBED_REQUEST_TIMEOUT = 30.0
+            mock_cfg.EMBED_CONNECT_TIMEOUT = 5.0
+            mock_cfg.EMBED_RETRY_BACKOFF_BASE = 2.0
+            # LLM 配置
+            mock_cfg.LLM_BASE_URL = "https://fake-llm.example.com"
+            mock_cfg.LLM_API_KEY = "test-llm"
+            mock_cfg.LLM_MODEL = "test-model"
+            mock_cfg.LLM_MAX_CONCURRENCY = 3
+            mock_cfg.LLM_MAX_RETRIES = 2
+            mock_cfg.LLM_REQUEST_TIMEOUT = 30.0
+            mock_cfg.LLM_CONNECT_TIMEOUT = 5.0
+            mock_cfg.LLM_RETRY_BACKOFF_BASE = 2.0
+            # Upload / chunking
+            mock_cfg.MAX_FILE_SIZE = 10 * 1024 * 1024
+            mock_cfg.CHUNK_MAX_CHARS = 1500
+            mock_cfg.CHUNK_OVERLAP = 50
+            # 其他
+            mock_cfg.PG_DSN = "postgresql://fake"
+            mock_cfg.PG_POOL_MIN = 1
+            mock_cfg.PG_POOL_MAX = 5
+            mock_cfg.PG_COMMAND_TIMEOUT = 30.0
+            mock_get_settings.return_value = mock_cfg
+            mock_setup_logging.return_value = MagicMock()
+
+            async def _run_lifespan():
+                results = {}
+
+                @asynccontextmanager
+                async def test_lifespan(app):
+                    async with real_lifespan(app) as _:
+                        results["retrieve_uc"] = getattr(app.state, "retrieve_uc", None)
+                        results["upload_doc_uc"] = getattr(app.state, "upload_doc_uc", None)
+                    yield
+
+                app = FastAPI(lifespan=test_lifespan)
+                async with app.router.lifespan_context(app):
+                    pass
+                return results
+
+            results = asyncio.run(_run_lifespan())
+            retrieve_uc = results["retrieve_uc"]
+            assert retrieve_uc is not None, "lifespan 应设置 app.state.retrieve_uc"
+            assert isinstance(retrieve_uc._reranker, NoopRerankProvider), (
+                f"禁用重排时应为 NoopRerankProvider，实际: {type(retrieve_uc._reranker).__name__}"
+            )
+            assert retrieve_uc._candidate_multiplier == 1, "禁用重排时 candidate_multiplier 应为 1"
+            assert retrieve_uc._min_candidates == 0, "禁用重排时 min_candidates 应为 0"
+
+    def test_rerank_enabled_uses_llm_reranker(self):
+        """RERANK_ENABLED=True 时，retrieve_uc 的 reranker 为 LLMRerankProvider 实例。"""
+        from contextlib import asynccontextmanager
+
+        from fastapi import FastAPI
+
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+        from ragnexus.composition import lifespan as real_lifespan
+
+        with (
+            patch(
+                "ragnexus.composition.asyncpg.create_pool",
+                new_callable=AsyncMock,
+            ) as mock_create_pool,
+            patch(
+                "ragnexus.composition.PgVectorStore",
+                autospec=True,
+            ) as mock_store_cls,
+            patch("ragnexus.composition.get_settings") as mock_get_settings,
+            patch("ragnexus.composition.setup_logging") as mock_setup_logging,
+            patch("ragnexus.composition.OpenAICompatibleLLMProvider"),
+        ):
+            mock_pool = MagicMock()
+            mock_create_pool.return_value = mock_pool
+            mock_pool.close = AsyncMock()
+
+            mock_store = mock_store_cls.return_value
+            mock_store.connect = AsyncMock()
+            mock_store.close = AsyncMock()
+            mock_store.pool = MagicMock()
+            mock_store.pool.fetchval = AsyncMock(return_value=1024)
+
+            mock_cfg = MagicMock()
+            mock_cfg.EMBED_DIM = 1024
+            mock_cfg.RERANK_ENABLED = True
+            mock_cfg.RERANK_CANDIDATE_MULTIPLIER = 3
+            mock_cfg.RERANK_MIN_CANDIDATES = 10
+            mock_cfg.RERANK_MAX_CANDIDATES = 20
+            mock_cfg.RERANK_CHUNK_MAX_CHARS = 1000
+            mock_cfg.RERANK_CACHE_SIMILARITY_THRESHOLD = 0.95
+            mock_cfg.RERANK_CACHE_MAX_ENTRIES = 100
+            mock_cfg.RERANK_CACHE_TTL_SECONDS = 300
+            mock_cfg.RERANK_TEMPERATURE = 0.0
+            # Embedder
+            mock_cfg.EMBED_BASE_URL = "https://fake.example.com"
+            mock_cfg.EMBED_API_KEY = "test"
+            mock_cfg.EMBED_MODEL = "text-embedding-v3"
+            mock_cfg.EMBED_BATCH_SIZE = 50
+            mock_cfg.EMBED_MAX_CONCURRENCY = 5
+            mock_cfg.EMBED_MAX_RETRIES = 3
+            mock_cfg.EMBED_REQUEST_TIMEOUT = 30.0
+            mock_cfg.EMBED_CONNECT_TIMEOUT = 5.0
+            mock_cfg.EMBED_RETRY_BACKOFF_BASE = 2.0
+            # LLM
+            mock_cfg.LLM_BASE_URL = "https://fake-llm.example.com"
+            mock_cfg.LLM_API_KEY = "test-llm"
+            mock_cfg.LLM_MODEL = "test-model"
+            mock_cfg.LLM_MAX_CONCURRENCY = 3
+            mock_cfg.LLM_MAX_RETRIES = 2
+            mock_cfg.LLM_REQUEST_TIMEOUT = 30.0
+            mock_cfg.LLM_CONNECT_TIMEOUT = 5.0
+            mock_cfg.LLM_RETRY_BACKOFF_BASE = 2.0
+            # Upload / chunking
+            mock_cfg.MAX_FILE_SIZE = 10 * 1024 * 1024
+            mock_cfg.CHUNK_MAX_CHARS = 1500
+            mock_cfg.CHUNK_OVERLAP = 50
+            # 其他
+            mock_cfg.PG_DSN = "postgresql://fake"
+            mock_cfg.PG_POOL_MIN = 1
+            mock_cfg.PG_POOL_MAX = 5
+            mock_cfg.PG_COMMAND_TIMEOUT = 30.0
+            mock_get_settings.return_value = mock_cfg
+            mock_setup_logging.return_value = MagicMock()
+
+            async def _run_lifespan():
+                results = {}
+
+                @asynccontextmanager
+                async def test_lifespan(app):
+                    async with real_lifespan(app) as _:
+                        results["retrieve_uc"] = getattr(app.state, "retrieve_uc", None)
+                        results["upload_doc_uc"] = getattr(app.state, "upload_doc_uc", None)
+                    yield
+
+                app = FastAPI(lifespan=test_lifespan)
+                async with app.router.lifespan_context(app):
+                    pass
+                return results
+
+            results = asyncio.run(_run_lifespan())
+            retrieve_uc = results["retrieve_uc"]
+            assert retrieve_uc is not None, "lifespan 应设置 app.state.retrieve_uc"
+            assert isinstance(retrieve_uc._reranker, LLMRerankProvider), (
+                f"启用重排时应为 LLMRerankProvider，实际: {type(retrieve_uc._reranker).__name__}"
+            )
+            assert retrieve_uc._candidate_multiplier == 3, (
+                "启用重排时 candidate_multiplier 应为配置值"
+            )
+            assert retrieve_uc._min_candidates == 10, "启用重排时 min_candidates 应为配置值"
+
+    def test_upload_doc_is_wrapped_with_cache_invalidator(self):
+        """upload_doc_uc 被 CacheInvalidatingUploadUseCase 包装。"""
+        from contextlib import asynccontextmanager
+
+        from fastapi import FastAPI
+
+        from ragnexus.composition import (
+            CacheInvalidatingUploadUseCase,
+        )
+        from ragnexus.composition import (
+            lifespan as real_lifespan,
+        )
+
+        with (
+            patch(
+                "ragnexus.composition.asyncpg.create_pool",
+                new_callable=AsyncMock,
+            ) as mock_create_pool,
+            patch(
+                "ragnexus.composition.PgVectorStore",
+                autospec=True,
+            ) as mock_store_cls,
+            patch("ragnexus.composition.get_settings") as mock_get_settings,
+            patch("ragnexus.composition.setup_logging") as mock_setup_logging,
+            patch("ragnexus.composition.OpenAICompatibleLLMProvider"),
+        ):
+            mock_pool = MagicMock()
+            mock_create_pool.return_value = mock_pool
+            mock_pool.close = AsyncMock()
+
+            mock_store = mock_store_cls.return_value
+            mock_store.connect = AsyncMock()
+            mock_store.close = AsyncMock()
+            mock_store.pool = MagicMock()
+            mock_store.pool.fetchval = AsyncMock(return_value=1024)
+
+            mock_cfg = MagicMock()
+            mock_cfg.EMBED_DIM = 1024
+            mock_cfg.RERANK_ENABLED = False
+            mock_cfg.EMBED_BASE_URL = "https://fake.example.com"
+            mock_cfg.EMBED_API_KEY = "test"
+            mock_cfg.EMBED_MODEL = "text-embedding-v3"
+            mock_cfg.EMBED_BATCH_SIZE = 50
+            mock_cfg.EMBED_MAX_CONCURRENCY = 5
+            mock_cfg.EMBED_MAX_RETRIES = 3
+            mock_cfg.EMBED_REQUEST_TIMEOUT = 30.0
+            mock_cfg.EMBED_CONNECT_TIMEOUT = 5.0
+            mock_cfg.EMBED_RETRY_BACKOFF_BASE = 2.0
+            mock_cfg.LLM_BASE_URL = "https://fake-llm.example.com"
+            mock_cfg.LLM_API_KEY = "test-llm"
+            mock_cfg.LLM_MODEL = "test-model"
+            mock_cfg.LLM_MAX_CONCURRENCY = 3
+            mock_cfg.LLM_MAX_RETRIES = 2
+            mock_cfg.LLM_REQUEST_TIMEOUT = 30.0
+            mock_cfg.LLM_CONNECT_TIMEOUT = 5.0
+            mock_cfg.LLM_RETRY_BACKOFF_BASE = 2.0
+            mock_cfg.MAX_FILE_SIZE = 10 * 1024 * 1024
+            mock_cfg.CHUNK_MAX_CHARS = 1500
+            mock_cfg.CHUNK_OVERLAP = 50
+            mock_cfg.PG_DSN = "postgresql://fake"
+            mock_cfg.PG_POOL_MIN = 1
+            mock_cfg.PG_POOL_MAX = 5
+            mock_cfg.PG_COMMAND_TIMEOUT = 30.0
+            mock_get_settings.return_value = mock_cfg
+            mock_setup_logging.return_value = MagicMock()
+
+            async def _run_lifespan():
+                results = {}
+
+                @asynccontextmanager
+                async def test_lifespan(app):
+                    async with real_lifespan(app) as _:
+                        results["upload_doc_uc"] = getattr(app.state, "upload_doc_uc", None)
+                    yield
+
+                app = FastAPI(lifespan=test_lifespan)
+                async with app.router.lifespan_context(app):
+                    pass
+                return results
+
+            results = asyncio.run(_run_lifespan())
+            upload_doc_uc = results["upload_doc_uc"]
+            assert upload_doc_uc is not None, "lifespan 应设置 app.state.upload_doc_uc"
+            assert isinstance(upload_doc_uc, CacheInvalidatingUploadUseCase), (
+                f"上传用例应被包装，实际类型: {type(upload_doc_uc).__name__}"
+            )
diff --git a/tests/unit/application/test_retrieve.py b/tests/unit/application/test_retrieve.py
index 7c395b3..544e7af 100644
--- a/tests/unit/application/test_retrieve.py
+++ b/tests/unit/application/test_retrieve.py
@@ -1,19 +1,20 @@
 """Tests for RetrieveUseCase."""
 
 from unittest.mock import AsyncMock, patch
 
 import pytest
 
 from ragnexus.application.retrieve_use_case import RetrieveUseCase
 from ragnexus.core.errors import AppError
 from ragnexus.domain.models import SearchHit
+from ragnexus.adapters.rerank.noop import NoopRerankProvider
 
 
 @pytest.fixture
 def mock_kb_repo():
     return AsyncMock()
 
 
 @pytest.fixture
 def mock_embedder():
     return AsyncMock()
@@ -23,26 +24,34 @@ def mock_embedder():
 def mock_store():
     return AsyncMock()
 
 
 @pytest.fixture
 def mock_log_port():
     return AsyncMock()
 
 
 @pytest.fixture
-def use_case(mock_kb_repo, mock_embedder, mock_store, mock_log_port):
+def mock_reranker():
+    """RerankPort mock — 默认直通返回，各测试可按需覆盖 return_value。"""
+    m = AsyncMock()
+    return m
+
+
+@pytest.fixture
+def use_case(mock_kb_repo, mock_embedder, mock_store, mock_log_port, mock_reranker):
     return RetrieveUseCase(
         kb_repo=mock_kb_repo,
         embedder=mock_embedder,
         store=mock_store,
         log_port=mock_log_port,
+        reranker=mock_reranker,
     )
 
 
 @pytest.fixture
 def sample_hits():
     return [
         SearchHit(
             chunk_id="kb_test:0",
             kb_id="kb_test",
             doc_id="doc_1",
@@ -56,58 +65,83 @@ def sample_hits():
             doc_id="doc_1",
             score=0.85,
             text="another chunk",
             metadata={},
         ),
     ]
 
 
 @pytest.mark.asyncio
 async def test_retrieve_success(
-    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port, sample_hits
+    use_case,
+    mock_kb_repo,
+    mock_embedder,
+    mock_store,
+    mock_log_port,
+    mock_reranker,
+    sample_hits,
 ):
     """Valid query/kb_ids/top_k should embed, search, and return SearchHit list with scores."""
     kb_ids = ["kb_test"]
     top_k = 5
 
     mock_kb_repo.exists.return_value = True
     mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
     mock_store.search_by_vector.return_value = sample_hits
+    mock_reranker.rerank.return_value = sample_hits
 
     result = await use_case.execute(query="test query", kb_ids=kb_ids, top_k=top_k)
 
     assert result == sample_hits
     assert all(isinstance(h, SearchHit) for h in result)
     assert all(isinstance(h.score, float) for h in result)
 
     mock_embedder.embed.assert_awaited_once_with(["test query"])
-    mock_store.search_by_vector.assert_awaited_once_with([0.1, 0.2, 0.3], top_k, kb_ids)
+    # 默认 multiplier=1, min=0 → candidate_k == top_k
+    candidate_k = max(top_k * 1, top_k + 0)
+    mock_store.search_by_vector.assert_awaited_once_with(
+        [0.1, 0.2, 0.3], candidate_k, kb_ids
+    )
+    mock_reranker.rerank.assert_awaited_once_with(
+        query="test query",
+        query_vector=[0.1, 0.2, 0.3],
+        kb_ids=kb_ids,
+        chunks=sample_hits,
+        top_n=top_k,
+    )
     mock_kb_repo.exists.assert_awaited_once_with("kb_test")
 
     # log_port.log should have been called via create_task (fire-and-forget)
     # We just verify it was called (the task may or may not have completed)
     import asyncio
 
     await asyncio.sleep(0.01)  # yield to let the fire-and-forget task run
     mock_log_port.log.assert_awaited_once()
 
 
 @pytest.mark.asyncio
 async def test_retrieve_logs_biz_event(
-    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port, sample_hits
+    use_case,
+    mock_kb_repo,
+    mock_embedder,
+    mock_store,
+    mock_log_port,
+    mock_reranker,
+    sample_hits,
 ):
     """Retrieve completion emits BIZ_EVENT log in finally block."""
     import asyncio
 
     mock_kb_repo.exists.return_value = True
     mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
     mock_store.search_by_vector.return_value = sample_hits
+    mock_reranker.rerank.return_value = sample_hits
 
     with patch("ragnexus.core.logger.logger.info") as mock_info:
         await use_case.execute(query="test query", kb_ids=["kb_test"], top_k=5)
         await asyncio.sleep(0.01)  # yield to let the fire-and-forget task run
 
         # 找到 BIZ_EVENT 调用
         biz_calls = [
             call
             for call in mock_info.call_args_list
             if call.kwargs.get("extra", {}).get("event_type") == "BIZ_EVENT"
@@ -115,74 +149,90 @@ async def test_retrieve_logs_biz_event(
         assert len(biz_calls) == 1
         extra = biz_calls[0].kwargs["extra"]
         assert extra["event"] == "retrieve_completed"
         assert extra["kb_ids"] == ["kb_test"]
         assert extra["top_k"] == 5
         assert extra["hit_count"] == len(sample_hits)
         assert extra["latency_ms"] >= 0
 
 
 @pytest.mark.asyncio
-async def test_query_empty(use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port):
+async def test_query_empty(
+    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port
+):
     """Empty or whitespace-only query should raise ValidationError."""
     for bad_query in ("", "  "):
         with pytest.raises(AppError):
             await use_case.execute(query=bad_query, kb_ids=["kb_test"], top_k=5)
     mock_kb_repo.exists.assert_not_called()
     mock_embedder.embed.assert_not_called()
     mock_store.search_by_vector.assert_not_called()
 
 
 @pytest.mark.asyncio
-async def test_query_too_long(use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port):
+async def test_query_too_long(
+    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port
+):
     """Query longer than 2000 chars should raise ValidationError."""
     long_query = "A" * 2001
     with pytest.raises(AppError):
         await use_case.execute(query=long_query, kb_ids=["kb_test"], top_k=5)
     mock_kb_repo.exists.assert_not_called()
     mock_embedder.embed.assert_not_called()
     mock_store.search_by_vector.assert_not_called()
 
 
 @pytest.mark.asyncio
-async def test_kb_ids_empty(use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port):
+async def test_kb_ids_empty(
+    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port
+):
     """Empty kb_ids list should raise ValidationError."""
     with pytest.raises(AppError):
         await use_case.execute(query="test query", kb_ids=[], top_k=5)
     mock_kb_repo.exists.assert_not_called()
     mock_embedder.embed.assert_not_called()
     mock_store.search_by_vector.assert_not_called()
 
 
 @pytest.mark.asyncio
-async def test_kb_ids_too_many(use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port):
+async def test_kb_ids_too_many(
+    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port
+):
     """More than 5 kb_ids should raise ValidationError."""
     with pytest.raises(AppError):
-        await use_case.execute(query="test query", kb_ids=["a", "b", "c", "d", "e", "f"], top_k=5)
+        await use_case.execute(
+            query="test query", kb_ids=["a", "b", "c", "d", "e", "f"], top_k=5
+        )
     mock_kb_repo.exists.assert_not_called()
     mock_embedder.embed.assert_not_called()
     mock_store.search_by_vector.assert_not_called()
 
 
 @pytest.mark.asyncio
-async def test_top_k_oob(use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port):
+async def test_top_k_oob(
+    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port
+):
     """top_k < 1 or > 50 should raise ValidationError."""
     for bad_top_k in (0, 51):
         with pytest.raises(AppError):
-            await use_case.execute(query="test query", kb_ids=["kb_test"], top_k=bad_top_k)
+            await use_case.execute(
+                query="test query", kb_ids=["kb_test"], top_k=bad_top_k
+            )
     mock_kb_repo.exists.assert_not_called()
     mock_embedder.embed.assert_not_called()
     mock_store.search_by_vector.assert_not_called()
 
 
 @pytest.mark.asyncio
-async def test_kb_not_found(use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port):
+async def test_kb_not_found(
+    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port
+):
     """When any kb_id does not exist, should raise NotFoundError."""
     mock_kb_repo.exists.return_value = False
 
     with pytest.raises(AppError) as exc_info:
         await use_case.execute(query="test query", kb_ids=["kb_missing"], top_k=5)
 
     assert "kb_missing" in str(exc_info.value)
     mock_kb_repo.exists.assert_awaited_once_with("kb_missing")
     mock_embedder.embed.assert_not_called()
     mock_store.search_by_vector.assert_not_called()
@@ -206,27 +256,233 @@ async def test_multiple_kb_not_found(
             kb_ids=["kb_good", "kb_bad"],
             top_k=5,
         )
     assert "kb_bad" in str(exc_info.value)
     mock_embedder.embed.assert_not_called()
     mock_store.search_by_vector.assert_not_called()
 
 
 @pytest.mark.asyncio
 async def test_retrieve_log_fire_and_forget(
-    use_case, mock_kb_repo, mock_embedder, mock_store, mock_log_port, sample_hits
+    use_case,
+    mock_kb_repo,
+    mock_embedder,
+    mock_store,
+    mock_log_port,
+    mock_reranker,
+    sample_hits,
 ):
-    """When log_port.log raises, the exception should be swallowed (fire-and-forget)."""
     mock_kb_repo.exists.return_value = True
     mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
     mock_store.search_by_vector.return_value = sample_hits
+    mock_reranker.rerank.return_value = sample_hits
     mock_log_port.log.side_effect = RuntimeError("log failure")
 
     # Should not propagate the log error
     result = await use_case.execute(query="test query", kb_ids=["kb_test"], top_k=5)
 
     assert result == sample_hits
+    mock_reranker.rerank.assert_awaited_once()
     # Give the fire-and-forget task a chance to run/be swallowed
     import asyncio
 
     await asyncio.sleep(0.01)
     mock_log_port.log.assert_awaited_once()
+
+
+# ═══════════════════════════════════════════════════════════════════
+# rerank 注入测试 — Phase 4 Task 4.1-4.2
+# ═══════════════════════════════════════════════════════════════════
+
+
+@pytest.mark.asyncio
+async def test_candidate_k_uses_multiplier(
+    mock_kb_repo,
+    mock_embedder,
+    mock_store,
+    mock_log_port,
+    mock_reranker,
+    sample_hits,
+):
+    """candidate_multiplier=3, min_candidates=0 → candidate_k = top_k * 3。"""
+    uc = RetrieveUseCase(
+        kb_repo=mock_kb_repo,
+        embedder=mock_embedder,
+        store=mock_store,
+        log_port=mock_log_port,
+        reranker=mock_reranker,
+        candidate_multiplier=3,
+        min_candidates=0,
+    )
+    top_k = 5
+    mock_kb_repo.exists.return_value = True
+    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
+    mock_store.search_by_vector.return_value = sample_hits
+    mock_reranker.rerank.return_value = sample_hits[:2]
+
+    await uc.execute(query="q", kb_ids=["kb_test"], top_k=top_k)
+
+    # candidate_k = max(5*3, 5+0) = 15
+    mock_store.search_by_vector.assert_awaited_once_with(
+        [0.1, 0.2, 0.3], 15, ["kb_test"]
+    )
+
+
+@pytest.mark.asyncio
+async def test_candidate_k_uses_min_candidates(
+    mock_kb_repo,
+    mock_embedder,
+    mock_store,
+    mock_log_port,
+    mock_reranker,
+    sample_hits,
+):
+    """multiplier=1, min_candidates=10 → candidate_k = top_k + 10。"""
+    uc = RetrieveUseCase(
+        kb_repo=mock_kb_repo,
+        embedder=mock_embedder,
+        store=mock_store,
+        log_port=mock_log_port,
+        reranker=mock_reranker,
+        candidate_multiplier=1,
+        min_candidates=10,
+    )
+    top_k = 5
+    mock_kb_repo.exists.return_value = True
+    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
+    mock_store.search_by_vector.return_value = sample_hits
+    mock_reranker.rerank.return_value = sample_hits[:2]
+
+    await uc.execute(query="q", kb_ids=["kb_test"], top_k=top_k)
+
+    # candidate_k = max(5*1, 5+10) = 15
+    mock_store.search_by_vector.assert_awaited_once_with(
+        [0.1, 0.2, 0.3], 15, ["kb_test"]
+    )
+
+
+@pytest.mark.asyncio
+async def test_candidate_k_takes_max(
+    mock_kb_repo,
+    mock_embedder,
+    mock_store,
+    mock_log_port,
+    mock_reranker,
+    sample_hits,
+):
+    """multiplier=2 给出 10，min_candidates=2 给出 7，取大者 10。"""
+    uc = RetrieveUseCase(
+        kb_repo=mock_kb_repo,
+        embedder=mock_embedder,
+        store=mock_store,
+        log_port=mock_log_port,
+        reranker=mock_reranker,
+        candidate_multiplier=2,
+        min_candidates=2,
+    )
+    top_k = 5
+    mock_kb_repo.exists.return_value = True
+    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
+    mock_store.search_by_vector.return_value = sample_hits
+    mock_reranker.rerank.return_value = sample_hits[:2]
+
+    await uc.execute(query="q", kb_ids=["kb_test"], top_k=top_k)
+
+    # candidate_k = max(5*2, 5+2) = 10
+    mock_store.search_by_vector.assert_awaited_once_with(
+        [0.1, 0.2, 0.3], 10, ["kb_test"]
+    )
+
+
+@pytest.mark.asyncio
+async def test_rerank_called_with_correct_kwargs(
+    mock_kb_repo,
+    mock_embedder,
+    mock_store,
+    mock_log_port,
+    mock_reranker,
+    sample_hits,
+):
+    """reranker.rerank 使用正确的 keyword 参数调用。"""
+    uc = RetrieveUseCase(
+        kb_repo=mock_kb_repo,
+        embedder=mock_embedder,
+        store=mock_store,
+        log_port=mock_log_port,
+        reranker=mock_reranker,
+    )
+    top_k = 3
+    query = "什么是 RAG？"
+    kb_ids = ["kb_a", "kb_b"]
+    mock_kb_repo.exists.return_value = True
+    mock_embedder.embed.return_value = [[0.5, 0.6]]
+    mock_store.search_by_vector.return_value = sample_hits
+    mock_reranker.rerank.return_value = sample_hits[:1]
+
+    await uc.execute(query=query, kb_ids=kb_ids, top_k=top_k)
+
+    mock_reranker.rerank.assert_awaited_once_with(
+        query=query,
+        query_vector=[0.5, 0.6],
+        kb_ids=kb_ids,
+        chunks=sample_hits,
+        top_n=top_k,
+    )
+
+
+@pytest.mark.asyncio
+async def test_rerank_result_is_returned(
+    mock_kb_repo,
+    mock_embedder,
+    mock_store,
+    mock_log_port,
+    mock_reranker,
+    sample_hits,
+):
+    """execute() 返回 rerank 后的结果，而非原始向量召回结果。"""
+    uc = RetrieveUseCase(
+        kb_repo=mock_kb_repo,
+        embedder=mock_embedder,
+        store=mock_store,
+        log_port=mock_log_port,
+        reranker=mock_reranker,
+    )
+    # 构造一个与向量召回不同的 rerank 返回（顺序或内容不同）
+    reranked = [sample_hits[1], sample_hits[0]]  # 顺序反转
+    mock_kb_repo.exists.return_value = True
+    mock_embedder.embed.return_value = [[0.1, 0.2]]
+    mock_store.search_by_vector.return_value = sample_hits
+    mock_reranker.rerank.return_value = reranked
+
+    result = await uc.execute(query="q", kb_ids=["kb_test"], top_k=5)
+
+    assert result == reranked
+    assert result != sample_hits  # 证明返回的是 rerank 结果
+    mock_reranker.rerank.assert_awaited_once()
+
+
+@pytest.mark.asyncio
+async def test_noop_rerank_integration(
+    mock_kb_repo,
+    mock_embedder,
+    mock_store,
+    mock_log_port,
+    sample_hits,
+):
+    """使用真实 NoopRerankProvider — chunks[:top_n] 截断语义端到端。"""
+    uc = RetrieveUseCase(
+        kb_repo=mock_kb_repo,
+        embedder=mock_embedder,
+        store=mock_store,
+        log_port=mock_log_port,
+        reranker=NoopRerankProvider(),
+    )
+    top_k = 1
+    mock_kb_repo.exists.return_value = True
+    mock_embedder.embed.return_value = [[0.1, 0.2]]
+    mock_store.search_by_vector.return_value = sample_hits  # 2 条
+
+    result = await uc.execute(query="q", kb_ids=["kb_test"], top_k=top_k)
+
+    # NoopRerankProvider 返回 chunks[:top_n]，即只保留前 top_k 条
+    assert len(result) == 1
+    assert result[0] == sample_hits[0]
diff --git a/tests/unit/test_noop_rerank.py b/tests/unit/test_noop_rerank.py
index c2c6357..6227d6d 100644
--- a/tests/unit/test_noop_rerank.py
+++ b/tests/unit/test_noop_rerank.py
@@ -65,24 +65,23 @@ class TestNoopRerankProvider:
                 query_vector=[0.1],
                 kb_ids=["kb1"],
                 chunks=[],
                 top_n=5,
             )
 
         result = asyncio.run(_run())
         assert isinstance(result, list)
 
     def test_rerank_returns_same_chunks_no_modification(self) -> None:
-        """rerank() 直接返回原始 chunks，不排序、不截断。
+        """rerank() 直接返回原始 chunks，不排序，按 top_n 截断。
 
-        禁用重排时的直通行为：传入什么就返回什么，不做任何修改。
-        """
+        禁用重排时的直通行为：保持顺序不变，裁剪到 top_n。"""
         from ragnexus.adapters.rerank.noop import NoopRerankProvider
 
         provider = NoopRerankProvider()
 
         chunks = [
             SearchHit(
                 chunk_id="c1",
                 kb_id="kb_alpha",
                 doc_id="doc_a",
                 score=0.5,
@@ -111,62 +110,58 @@ class TestNoopRerankProvider:
             return await provider.rerank(
                 query="测试查询",
                 query_vector=[0.1, 0.2, 0.3],
                 kb_ids=["kb_alpha"],
                 chunks=chunks,
                 top_n=2,
             )
 
         result = asyncio.run(_run())
 
-        # 返回的列表长度与原始相同（不截断，忽略 top_n）
-        assert len(result) == 3, f"直通应返回全部 chunks，期望 3，实际 {len(result)}"
+        # 返回的列表长度为 top_n（截断到 top_n）
+        assert len(result) == 2, f"应截断到 top_n=2，期望 2，实际 {len(result)}"
 
-        # 返回的是同一批对象（is 检查），表示没有复制
-        assert result is chunks, f"rerank 应返回完全相同的列表对象"
+        # 截断后创建新列表对象
+        assert result is not chunks, "截断应创建新列表"
 
-        # 分值不变 — 不排序，保持原始顺序
+        # 分值不变 — 不排序，保持原始顺序（裁剪到 top_n）
         assert result[0].score == 0.5, "第一个元素分值不应改变"
         assert result[1].score == 0.9, "第二个元素分值不应改变"
-        assert result[2].score == 0.3, "第三个元素分值不应改变"
 
         # 所有字段保持不变
         assert result[0].chunk_id == "c1"
         assert result[0].text == "中等相关"
         assert result[0].metadata == {"page": 1}
         assert result[1].chunk_id == "c3"
         assert result[1].text == "高度相关"
         assert result[1].metadata == {"page": 3}
-        assert result[2].chunk_id == "c2"
-        assert result[2].text == "低相关"
-        assert result[2].metadata == {"page": 2}
 
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
 
-    def test_rerank_ignores_top_n(self) -> None:
-        """即使 top_n < len(chunks)，也应该返回全部 chunks（直通）。"""
+    def test_rerank_truncates_to_top_n(self) -> None:
+        """top_n < len(chunks) 时应截断到 top_n，防止返回超量 chunks。"""
         from ragnexus.adapters.rerank.noop import NoopRerankProvider
 
         provider = NoopRerankProvider()
 
         chunks = [
             SearchHit(
                 chunk_id=f"c{i}",
                 kb_id="kb1",
                 doc_id="d1",
                 score=float(i),
@@ -175,25 +170,25 @@ class TestNoopRerankProvider:
             )
             for i in range(5)
         ]
 
         async def _run() -> list[SearchHit]:
             return await provider.rerank(
                 query="q",
                 query_vector=[0.0],
                 kb_ids=["kb1"],
                 chunks=chunks,
-                top_n=2,  # 请求只取前2，但直通应忽略
+                top_n=2,  # 请求只取前2，会截断
             )
 
         result = asyncio.run(_run())
-        assert len(result) == 5, f"直通应返回全部 5 个 chunks，实际 {len(result)}"
+        assert len(result) == 2, f"应截断到 top_n=2，期望 2，实际 {len(result)}"
 
     def test_clear_cache_is_noop(self) -> None:
         """clear_cache() 应为空实现，不抛异常。"""
         from ragnexus.adapters.rerank.noop import NoopRerankProvider
 
         provider = NoopRerankProvider()
 
         # 不应抛出任何异常
         async def _run() -> None:
             await provider.clear_cache("kb_any")
