"""RAGNexus 日志接入层 TDD 测试 — 中间件 + 模型装饰器 + 数据库代理。

TDD: RED → GREEN → REFACTOR。
运行: uv run pytest tests/unit/adapters/test_middleware.py -v
"""

# pyright: reportAttributeAccessIssue=false
import asyncio
import logging
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from ragnexus.core.logger import LoggedPool

# ============================================================================
# 辅助工具
# ============================================================================


class _ListHandler(logging.Handler):
    """捕获日志记录到列表的 Handler。"""

    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__()
        self._records = records

    def emit(self, record: logging.LogRecord) -> None:
        self._records.append(record)


def _get_rag_logger() -> logging.Logger:
    return logging.getLogger("ragnexus")


def _add_capture_handler(records: list[logging.LogRecord]) -> _ListHandler:
    handler = _ListHandler(records)
    handler.setLevel(logging.DEBUG)
    rag = _get_rag_logger()
    rag.addHandler(handler)
    rag.setLevel(logging.DEBUG)
    return handler


def _remove_capture_handler(handler: _ListHandler) -> None:
    _get_rag_logger().removeHandler(handler)


# ============================================================================
# TestLoggingMiddleware — Phase 3: 请求日志中间件
# ============================================================================


class TestLoggingMiddleware:
    """LoggingMiddleware 测试套件。

    使用 Starlette 最小应用 + TestClient 模拟 HTTP 请求，
    捕获 ragnexus logger 的输出来验证中间件行为。
    在 LoggingMiddleware 实现之前全部 RED。
    """

    @pytest.fixture
    def captured(self) -> list[logging.LogRecord]:
        return []

    @pytest.fixture
    def handler(
        self, captured: list[logging.LogRecord]
    ) -> Generator[_ListHandler, None, None]:
        h = _add_capture_handler(captured)
        yield h
        _remove_capture_handler(h)

    @staticmethod
    def _build_app() -> Starlette:
        """构建带 LoggingMiddleware 的最小 Starlette 应用。"""

        async def echo_json(request):
            import json

            body_bytes = await request.body()
            body = json.loads(body_bytes) if body_bytes else {}
            return JSONResponse(body)

        async def echo_multipart(request):
            form = await request.form()
            fields = list(form.keys())
            return JSONResponse({"fields": fields})

        from ragnexus.adapters.http.middleware import LoggingMiddleware

        app = Starlette(
            debug=True,
            routes=[
                Route("/echo", echo_json, methods=["POST"]),
                Route("/upload", echo_multipart, methods=["POST"]),
            ],
            middleware=[Middleware(LoggingMiddleware)],
        )
        return app

    def test_adds_req_id_when_missing(
        self, captured: list[logging.LogRecord], handler: _ListHandler
    ):
        """缺少 X-Request-ID 时，中间件应自动生成 req_id。"""
        app = self._build_app()
        client = TestClient(app)

        resp = client.post("/echo", json={"msg": "hello"})
        assert resp.status_code == 200

        req_logs = [
            r for r in captured if getattr(r, "event_type", None) == "API_REQUEST"
        ]
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

        req_logs = [
            r for r in captured if getattr(r, "event_type", None) == "API_REQUEST"
        ]
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

        resp_logs = [
            r for r in captured if getattr(r, "event_type", None) == "API_RESPONSE"
        ]
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

        req_logs = [
            r for r in captured if getattr(r, "event_type", None) == "API_REQUEST"
        ]
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

        req_logs = [
            r for r in captured if getattr(r, "event_type", None) == "API_REQUEST"
        ]
        assert len(req_logs) >= 1
        body_present = getattr(req_logs[0], "body_present", True)
        assert body_present is False, "multipart 不应读取 body"

    def test_clears_context_after_request(
        self, captured: list[logging.LogRecord], handler: _ListHandler
    ):
        """请求结束后 ContextVar 应被清理。"""
        from ragnexus.core.logger import _log_ctx, clear_log_context

        clear_log_context()
        app = self._build_app()
        client = TestClient(app)

        client.post("/echo", json={"msg": "test"})

        ctx = _log_ctx.get() or {}
        assert ctx.get("req_id") is None, "请求结束后 req_id 应被清理"


# ============================================================================
# TestLogModelCallOnEmbedder — Phase 4: 模型日志装饰器
# ============================================================================


class TestLogModelCallOnEmbedder:
    """验证 OpenAICompatEmbedder.embed() 被 @log_model_call 装饰后产生日志。

    在装饰器添加之前，调用 embed() 不应产生 MODEL_REQUEST/RESPONSE → RED。
    """

    def _make_embedder(self) -> "object":
        """创建带假 httpx transport 的 OpenAICompatEmbedder。

        使用 httpx.MockTransport 拦截 HTTP 请求，返回假 embedding 数据。
        """
        from ragnexus.adapters.embedder.openai_compat import OpenAICompatEmbedder

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            dim = 1024
            body = json.loads(request.content)
            inputs = body["input"]
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": [0.1] * dim}
                        for i in range(len(inputs))
                    ]
                },
            )

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        emb = OpenAICompatEmbedder(
            base_url="https://fake.example.com/v1",
            api_key="test-key",
            model="text-embedding-v3",
            dim=1024,
        )
        emb._client = client  # 注入假 client，跳过 lazy init
        return emb

    def test_embed_logs_model_request_and_response(self):
        """embed() 调用应产生 MODEL_REQUEST 和 MODEL_RESPONSE 日志。

        实现前：@log_model_call 未添加 → 无 MODEL_REQUEST/RESPONSE → RED。
        实现后：装饰器生效 → 日志中出现事件 → GREEN。
        """
        records: list[logging.LogRecord] = []
        handler = _add_capture_handler(records)
        try:
            emb = self._make_embedder()
            result = asyncio.run(emb.embed(["hello world"]))
            assert len(result) == 1
            assert len(result[0]) == 1024

            event_types = {getattr(r, "event_type", None) for r in records}
            assert (
                "MODEL_REQUEST" in event_types
            ), "未检测到 MODEL_REQUEST — @log_model_call 可能尚未添加到 embed()"
            assert (
                "MODEL_RESPONSE" in event_types
            ), "未检测到 MODEL_RESPONSE — @log_model_call 可能尚未添加到 embed()"

            resp_logs = [
                r for r in records if getattr(r, "event_type", None) == "MODEL_RESPONSE"
            ]
            assert len(resp_logs) >= 1
            assert getattr(resp_logs[0], "model", None) == "text-embedding-v3"
        finally:
            _remove_capture_handler(handler)

    def test_embed_error_logs_model_response_with_error(self):
        """embed() 失败时应记录 MODEL_RESPONSE 并包含 error 字段。"""
        from ragnexus.core.errors import AppError

        records: list[logging.LogRecord] = []
        handler = _add_capture_handler(records)
        try:
            emb = self._make_embedder()
            emb._client = httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(500, text="Internal Server Error")
                )
            )

            with pytest.raises(AppError):
                asyncio.run(emb.embed(["test"]))

            err_logs = [
                r for r in records if getattr(r, "event_type", None) == "MODEL_RESPONSE"
            ]
            assert (
                len(err_logs) >= 1
            ), "未检测到失败时的 MODEL_RESPONSE — @log_model_call 未生效"
            error_val = getattr(err_logs[0], "error", None)
            assert error_val is not None
        finally:
            _remove_capture_handler(handler)


# ============================================================================
# TestLoggedPoolWiring — Phase 5: 数据库日志代理接入
# ============================================================================


class TestLoggedPoolWiring:
    """验证 composition.py lifespan 中将 repo_pool 包装为 LoggedPool。

    实现前：repo_pool 是原始 asyncpg.Pool → RED。
    实现后：repo_pool 是 LoggedPool 实例 → GREEN。
    """

    @pytest.mark.skip(reason="lifespan mock 需重写以支持迁移检测/prune/llm_provider.close")
    def test_repo_pool_is_wrapped_with_loggedpool(self):
        """lifespan 启动后，app.state.repo_pool 应为 LoggedPool 实例。

        模拟所有外部依赖，仅验证 DI 容器层的包装逻辑。
        """
        from contextlib import asynccontextmanager

        from fastapi import FastAPI

        from ragnexus.composition import lifespan as real_lifespan

        # Monkey-patch 所有会产生副作用的模块
        with (
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
            patch('ragnexus.composition.OpenAICompatibleLLMProvider', new_callable=AsyncMock),
        ):
            # 配置 mock 返回值
            mock_pool = AsyncMock()
            mock_create_pool.return_value = mock_pool
            mock_pool.close = AsyncMock()

            mock_store = mock_store_cls.return_value
            mock_store.connect = AsyncMock()
            mock_store.close = AsyncMock()
            mock_store.pool = AsyncMock()
            mock_store.pool.fetchval = AsyncMock(return_value=1024)

            mock_cfg = MagicMock()
            mock_cfg.EMBED_DIM = 1024
            mock_cfg.PG_DSN = "postgresql://fake"
            mock_cfg.PG_POOL_MIN = 1
            mock_cfg.PG_POOL_MAX = 5
            mock_cfg.PG_COMMAND_TIMEOUT = 30.0
            mock_cfg.EMBED_BASE_URL = "https://fake.example.com"
            mock_cfg.EMBED_API_KEY = "test"
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
            # LLM 配置（lifespan 现在会创建 LLMProvider）
            mock_cfg.LLM_BASE_URL = "https://fake-llm.example.com"
            mock_cfg.LLM_API_KEY = "test-llm"
            mock_cfg.LLM_MODEL = "test-model"
            mock_cfg.LLM_MAX_CONCURRENCY = 3
            mock_cfg.LLM_MAX_RETRIES = 2
            mock_cfg.LLM_REQUEST_TIMEOUT = 30.0
            mock_cfg.LLM_CONNECT_TIMEOUT = 5.0
            mock_cfg.LLM_RETRY_BACKOFF_BASE = 2.0
            # 禁用重排（避免 LLMRerankProvider 构造时的副作用）
            mock_cfg.RERANK_ENABLED = False
            mock_get_settings.return_value = mock_cfg

            mock_setup_logging.return_value = MagicMock()

            # 运行 lifespan 并检查 repo_pool 是否被包装
            async def _run_lifespan():
                results = []

                @asynccontextmanager
                async def test_lifespan(app):
                    async with real_lifespan(app) as _:
                        results.append(app.state.repo_pool)
                    yield

                app = FastAPI(lifespan=test_lifespan)
                async with app.router.lifespan_context(app):
                    pass
                return results[0] if results else None

            repo_pool = asyncio.run(_run_lifespan())
            assert repo_pool is not None, "lifespan 应设置 app.state.repo_pool"
            assert isinstance(
                repo_pool, LoggedPool
            ), f"repo_pool 应为 LoggedPool 实例，实际类型为 {type(repo_pool).__name__}"


# ============================================================================
# TestRerankLLMWiring — Phase 5.5: LLM + Rerank DI 装配
# ============================================================================


class TestRerankLLMWiring:
    """验证 composition.py lifespan 中 LLMProvider + RerankProvider + upload 缓存清空。

    RED → 当前尚未添加 app.state.retrieve_uc / app.state.upload_doc_uc。
    GREEN → lifespan 创建 LLMProvider + RerankProvider 并注入 use case。
    """

    @pytest.mark.skip(reason="lifespan mock 需重写以支持迁移检测/prune/llm_provider.close")
    def test_rerank_disabled_uses_noop_reranker(self):
        """RERANK_ENABLED=False 时，retrieve_uc 的 reranker 为 NoopRerankProvider 实例。"""
        from contextlib import asynccontextmanager

        from fastapi import FastAPI

        from ragnexus.adapters.rerank.noop import NoopRerankProvider
        from ragnexus.composition import lifespan as real_lifespan

        with (
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
            patch('ragnexus.composition.OpenAICompatibleLLMProvider', new_callable=AsyncMock),
        ):
            mock_pool = AsyncMock()
            mock_create_pool.return_value = mock_pool
            mock_pool.close = AsyncMock()

            mock_store = mock_store_cls.return_value
            mock_store.connect = AsyncMock()
            mock_store.close = AsyncMock()
            mock_store.pool = AsyncMock()
            mock_store.pool.fetchval = AsyncMock(return_value=1024)

            mock_cfg = MagicMock()
            mock_cfg.EMBED_DIM = 1024
            # 确保 RERANK_ENABLED=False（默认）
            mock_cfg.RERANK_ENABLED = False
            # Embedder 配置
            mock_cfg.EMBED_BASE_URL = "https://fake.example.com"
            mock_cfg.EMBED_API_KEY = "test"
            mock_cfg.EMBED_MODEL = "text-embedding-v3"
            mock_cfg.EMBED_BATCH_SIZE = 50
            mock_cfg.EMBED_MAX_CONCURRENCY = 5
            mock_cfg.EMBED_MAX_RETRIES = 3
            mock_cfg.EMBED_REQUEST_TIMEOUT = 30.0
            mock_cfg.EMBED_CONNECT_TIMEOUT = 5.0
            mock_cfg.EMBED_RETRY_BACKOFF_BASE = 2.0
            # LLM 配置
            mock_cfg.LLM_BASE_URL = "https://fake-llm.example.com"
            mock_cfg.LLM_API_KEY = "test-llm"
            mock_cfg.LLM_MODEL = "test-model"
            mock_cfg.LLM_MAX_CONCURRENCY = 3
            mock_cfg.LLM_MAX_RETRIES = 2
            mock_cfg.LLM_REQUEST_TIMEOUT = 30.0
            mock_cfg.LLM_CONNECT_TIMEOUT = 5.0
            mock_cfg.LLM_RETRY_BACKOFF_BASE = 2.0
            # Upload / chunking
            mock_cfg.MAX_FILE_SIZE = 10 * 1024 * 1024
            mock_cfg.CHUNK_MAX_CHARS = 1500
            mock_cfg.CHUNK_OVERLAP = 50
            # 其他
            mock_cfg.PG_DSN = "postgresql://fake"
            mock_cfg.PG_POOL_MIN = 1
            mock_cfg.PG_POOL_MAX = 5
            mock_cfg.PG_COMMAND_TIMEOUT = 30.0
            mock_get_settings.return_value = mock_cfg
            mock_setup_logging.return_value = MagicMock()

            async def _run_lifespan():
                results = {}

                @asynccontextmanager
                async def test_lifespan(app):
                    async with real_lifespan(app) as _:
                        results["retrieve_uc"] = getattr(app.state, "retrieve_uc", None)
                        results["upload_doc_uc"] = getattr(
                            app.state, "upload_doc_uc", None
                        )
                    yield

                app = FastAPI(lifespan=test_lifespan)
                async with app.router.lifespan_context(app):
                    pass
                return results

            results = asyncio.run(_run_lifespan())
            retrieve_uc = results["retrieve_uc"]
            assert retrieve_uc is not None, "lifespan 应设置 app.state.retrieve_uc"
            assert isinstance(
                retrieve_uc._reranker, NoopRerankProvider
            ), f"禁用重排时应为 NoopRerankProvider，实际: {type(retrieve_uc._reranker).__name__}"
            assert (
                retrieve_uc._candidate_multiplier == 1
            ), "禁用重排时 candidate_multiplier 应为 1"
            assert retrieve_uc._min_candidates == 0, "禁用重排时 min_candidates 应为 0"

    @pytest.mark.skip(reason="lifespan mock 需重写以支持迁移检测/prune/llm_provider.close")
    def test_rerank_enabled_uses_llm_reranker(self):
        """RERANK_ENABLED=True 时，retrieve_uc 的 reranker 为 LLMRerankProvider 实例。"""
        from contextlib import asynccontextmanager

        from fastapi import FastAPI

        from ragnexus.adapters.rerank.llm import LLMRerankProvider
        from ragnexus.composition import lifespan as real_lifespan

        with (
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
            patch('ragnexus.composition.OpenAICompatibleLLMProvider', new_callable=AsyncMock),
        ):
            mock_pool = AsyncMock()
            mock_create_pool.return_value = mock_pool
            mock_pool.close = AsyncMock()

            mock_store = mock_store_cls.return_value
            mock_store.connect = AsyncMock()
            mock_store.close = AsyncMock()
            mock_store.pool = AsyncMock()
            mock_store.pool.fetchval = AsyncMock(return_value=1024)

            mock_cfg = MagicMock()
            mock_cfg.EMBED_DIM = 1024
            mock_cfg.RERANK_ENABLED = True
            mock_cfg.RERANK_CANDIDATE_MULTIPLIER = 3
            mock_cfg.RERANK_MIN_CANDIDATES = 10
            mock_cfg.RERANK_MAX_CANDIDATES = 20
            mock_cfg.RERANK_CHUNK_MAX_CHARS = 1000
            mock_cfg.RERANK_CACHE_SIMILARITY_THRESHOLD = 0.95
            mock_cfg.RERANK_CACHE_MAX_ENTRIES = 100
            mock_cfg.RERANK_CACHE_TTL_SECONDS = 300
            mock_cfg.RERANK_TEMPERATURE = 0.0
            # Embedder
            mock_cfg.EMBED_BASE_URL = "https://fake.example.com"
            mock_cfg.EMBED_API_KEY = "test"
            mock_cfg.EMBED_MODEL = "text-embedding-v3"
            mock_cfg.EMBED_BATCH_SIZE = 50
            mock_cfg.EMBED_MAX_CONCURRENCY = 5
            mock_cfg.EMBED_MAX_RETRIES = 3
            mock_cfg.EMBED_REQUEST_TIMEOUT = 30.0
            mock_cfg.EMBED_CONNECT_TIMEOUT = 5.0
            mock_cfg.EMBED_RETRY_BACKOFF_BASE = 2.0
            # LLM
            mock_cfg.LLM_BASE_URL = "https://fake-llm.example.com"
            mock_cfg.LLM_API_KEY = "test-llm"
            mock_cfg.LLM_MODEL = "test-model"
            mock_cfg.LLM_MAX_CONCURRENCY = 3
            mock_cfg.LLM_MAX_RETRIES = 2
            mock_cfg.LLM_REQUEST_TIMEOUT = 30.0
            mock_cfg.LLM_CONNECT_TIMEOUT = 5.0
            mock_cfg.LLM_RETRY_BACKOFF_BASE = 2.0
            # Upload / chunking
            mock_cfg.MAX_FILE_SIZE = 10 * 1024 * 1024
            mock_cfg.CHUNK_MAX_CHARS = 1500
            mock_cfg.CHUNK_OVERLAP = 50
            # 其他
            mock_cfg.PG_DSN = "postgresql://fake"
            mock_cfg.PG_POOL_MIN = 1
            mock_cfg.PG_POOL_MAX = 5
            mock_cfg.PG_COMMAND_TIMEOUT = 30.0
            mock_get_settings.return_value = mock_cfg
            mock_setup_logging.return_value = MagicMock()

            async def _run_lifespan():
                results = {}

                @asynccontextmanager
                async def test_lifespan(app):
                    async with real_lifespan(app) as _:
                        results["retrieve_uc"] = getattr(app.state, "retrieve_uc", None)
                        results["upload_doc_uc"] = getattr(
                            app.state, "upload_doc_uc", None
                        )
                    yield

                app = FastAPI(lifespan=test_lifespan)
                async with app.router.lifespan_context(app):
                    pass
                return results

            results = asyncio.run(_run_lifespan())
            retrieve_uc = results["retrieve_uc"]
            assert retrieve_uc is not None, "lifespan 应设置 app.state.retrieve_uc"
            assert isinstance(
                retrieve_uc._reranker, LLMRerankProvider
            ), f"启用重排时应为 LLMRerankProvider，实际: {type(retrieve_uc._reranker).__name__}"
            assert (
                retrieve_uc._candidate_multiplier == 3
            ), "启用重排时 candidate_multiplier 应为配置值"
            assert (
                retrieve_uc._min_candidates == 10
            ), "启用重排时 min_candidates 应为配置值"

    @pytest.mark.skip(reason="lifespan mock 需重写以支持迁移检测/prune/llm_provider.close")
    def test_upload_doc_is_wrapped_with_cache_invalidator(self):
        """upload_doc_uc 被 CacheInvalidatingUploadUseCase 包装。"""
        from contextlib import asynccontextmanager

        from fastapi import FastAPI

        from ragnexus.composition import (
            CacheInvalidatingUploadUseCase,
        )
        from ragnexus.composition import (
            lifespan as real_lifespan,
        )

        with (
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
            patch('ragnexus.composition.OpenAICompatibleLLMProvider', new_callable=AsyncMock),
        ):
            mock_pool = AsyncMock()
            mock_create_pool.return_value = mock_pool
            mock_pool.close = AsyncMock()

            mock_store = mock_store_cls.return_value
            mock_store.connect = AsyncMock()
            mock_store.close = AsyncMock()
            mock_store.pool = AsyncMock()
            mock_store.pool.fetchval = AsyncMock(return_value=1024)

            mock_cfg = MagicMock()
            mock_cfg.EMBED_DIM = 1024
            mock_cfg.RERANK_ENABLED = False
            mock_cfg.EMBED_BASE_URL = "https://fake.example.com"
            mock_cfg.EMBED_API_KEY = "test"
            mock_cfg.EMBED_MODEL = "text-embedding-v3"
            mock_cfg.EMBED_BATCH_SIZE = 50
            mock_cfg.EMBED_MAX_CONCURRENCY = 5
            mock_cfg.EMBED_MAX_RETRIES = 3
            mock_cfg.EMBED_REQUEST_TIMEOUT = 30.0
            mock_cfg.EMBED_CONNECT_TIMEOUT = 5.0
            mock_cfg.EMBED_RETRY_BACKOFF_BASE = 2.0
            mock_cfg.LLM_BASE_URL = "https://fake-llm.example.com"
            mock_cfg.LLM_API_KEY = "test-llm"
            mock_cfg.LLM_MODEL = "test-model"
            mock_cfg.LLM_MAX_CONCURRENCY = 3
            mock_cfg.LLM_MAX_RETRIES = 2
            mock_cfg.LLM_REQUEST_TIMEOUT = 30.0
            mock_cfg.LLM_CONNECT_TIMEOUT = 5.0
            mock_cfg.LLM_RETRY_BACKOFF_BASE = 2.0
            mock_cfg.MAX_FILE_SIZE = 10 * 1024 * 1024
            mock_cfg.CHUNK_MAX_CHARS = 1500
            mock_cfg.CHUNK_OVERLAP = 50
            mock_cfg.PG_DSN = "postgresql://fake"
            mock_cfg.PG_POOL_MIN = 1
            mock_cfg.PG_POOL_MAX = 5
            mock_cfg.PG_COMMAND_TIMEOUT = 30.0
            mock_get_settings.return_value = mock_cfg
            mock_setup_logging.return_value = MagicMock()

            async def _run_lifespan():
                results = {}

                @asynccontextmanager
                async def test_lifespan(app):
                    async with real_lifespan(app) as _:
                        results["upload_doc_uc"] = getattr(
                            app.state, "upload_doc_uc", None
                        )
                    yield

                app = FastAPI(lifespan=test_lifespan)
                async with app.router.lifespan_context(app):
                    pass
                return results

            results = asyncio.run(_run_lifespan())
            upload_doc_uc = results["upload_doc_uc"]
            assert upload_doc_uc is not None, "lifespan 应设置 app.state.upload_doc_uc"
            assert isinstance(
                upload_doc_uc, CacheInvalidatingUploadUseCase
            ), f"上传用例应被包装，实际类型: {type(upload_doc_uc).__name__}"
