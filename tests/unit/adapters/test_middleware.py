"""RAGNexus 日志接入层 TDD 测试 — 中间件 + 模型装饰器 + 数据库代理。

TDD: RED → GREEN → REFACTOR。
运行: uv run pytest tests/unit/adapters/test_middleware.py -v
"""

# pyright: reportAttributeAccessIssue=false
import asyncio
import logging
from collections.abc import Generator
from contextlib import asynccontextmanager, contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from ragnexus.core.logger import LoggedPool
from ragnexus.domain.models import UploadResult

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


def _make_lifespan_cfg(overrides: dict[str, Any] | None = None) -> MagicMock:
    """构造 lifespan 期望的 settings MagicMock，默认 RERANK_ENABLED=False。"""
    cfg = MagicMock()
    cfg.EMBED_DIM = 1024
    cfg.PG_DSN = "postgresql://fake"
    cfg.PG_POOL_MIN = 1
    cfg.PG_POOL_MAX = 5
    cfg.PG_COMMAND_TIMEOUT = 30.0
    cfg.EMBED_BASE_URL = "https://fake.example.com"
    cfg.EMBED_API_KEY = "test"
    cfg.EMBED_MODEL = "text-embedding-v3"
    cfg.EMBED_BATCH_SIZE = 50
    cfg.EMBED_MAX_CONCURRENCY = 5
    cfg.EMBED_MAX_RETRIES = 3
    cfg.EMBED_REQUEST_TIMEOUT = 30.0
    cfg.EMBED_CONNECT_TIMEOUT = 5.0
    cfg.EMBED_RETRY_BACKOFF_BASE = 2.0
    cfg.MAX_FILE_SIZE = 10 * 1024 * 1024
    cfg.CHUNK_MAX_CHARS = 1500
    cfg.CHUNK_OVERLAP = 50
    cfg.LLM_BASE_URL = "https://fake-llm.example.com"
    cfg.LLM_API_KEY = "test-llm"
    cfg.LLM_MODEL = "test-model"
    cfg.LLM_MAX_CONCURRENCY = 3
    cfg.LLM_MAX_RETRIES = 2
    cfg.LLM_REQUEST_TIMEOUT = 30.0
    cfg.LLM_CONNECT_TIMEOUT = 5.0
    cfg.LLM_RETRY_BACKOFF_BASE = 2.0
    cfg.RERANK_ENABLED = False
    cfg.RERANK_CANDIDATE_MULTIPLIER = 3
    cfg.RERANK_MIN_CANDIDATES = 10
    cfg.RERANK_MAX_CANDIDATES = 20
    cfg.RERANK_CHUNK_MAX_CHARS = 1000
    cfg.RERANK_CACHE_SIMILARITY_THRESHOLD = 0.95
    cfg.RERANK_CACHE_MAX_ENTRIES = 100
    cfg.RERANK_CACHE_TTL_SECONDS = 300
    cfg.RERANK_TEMPERATURE = 0.0
    cfg.REWRITE_ENABLED = False
    cfg.REWRITE_CACHE_SIMILARITY_THRESHOLD = 0.95
    cfg.REWRITE_CACHE_MAX_ENTRIES = 100
    cfg.REWRITE_CACHE_TTL_SECONDS = 300
    cfg.REWRITE_TEMPERATURE = 0.0
    for k, v in (overrides or {}).items():
        setattr(cfg, k, v)
    return cfg


@contextmanager
def _patched_lifespan(cfg_overrides: dict[str, Any] | None = None):
    """Patch composition.py 中所有 lifespan 副作用，返回 cfg。

    设计要点：
    - asyncpg.create_pool 调用两次（store 池 + repo 池），同一个 AsyncMock 实例返回给两边。
    - _raw_repo_pool.fetchval 必须为 AsyncMock（lifespan 检测 alembic_version）。
    - mock_store.pool.fetchval 在 lifespan 启动后被 await，必须返回 int。
    - _startup_cleanup 和 _periodic_log_cleanup 是 fire-and-forget 任务，
      通过把 asyncio.create_task 替换为 no-op 抑制，避免 race teardown。
    - PgKnowledgeBaseRepository / PgRetrieveLogRepository 替换为 AsyncMock 实例，
      否则 lifespan 会用真实类去 pool 上做查询。
    """
    cfg = _make_lifespan_cfg(cfg_overrides)

    # asyncpg pool mock — 两次 create_pool 调用返回同一个对象
    raw_pool = AsyncMock(name="asyncpg_pool")
    raw_pool.close = AsyncMock()
    raw_pool.fetchval = AsyncMock(return_value=0)
    mock_create_pool = AsyncMock(return_value=raw_pool)

    # PgVectorStore mock — 真实类构造后，调用其 .connect/.pool.fetchval
    store_inner = AsyncMock(name="PgVectorStore_instance")
    store_inner.pool = AsyncMock(name="store_pool_proxy")
    store_inner.pool.fetchval = AsyncMock(return_value=cfg.EMBED_DIM)
    store_inner.connect = AsyncMock()
    store_inner.close = AsyncMock()

    # LLMProvider / Embedder — 构造后调用 .close()
    mock_llm = AsyncMock(name="llm_provider")
    mock_llm.close = AsyncMock()
    mock_embedder = AsyncMock(name="embedder")
    mock_embedder.close = AsyncMock()

    # Repo mocks — 所有方法都是 AsyncMock（构造时不调用，使用时才 await）
    mock_kb_repo = AsyncMock(name="kb_repo")
    mock_log_repo = AsyncMock(name="log_repo")
    mock_log_repo.prune = AsyncMock(return_value=0)

    log_listener = MagicMock(name="log_listener")
    log_listener.stop = MagicMock()

    def _fake_create_task(coro):  # noqa: ANN001
        """替换 asyncio.create_task 为 no-op，避免清理任务 race teardown。"""
        try:
            coro.close()
        except Exception:
            pass
        return MagicMock(name="fake_task")

    with (
        patch("ragnexus.composition.asyncpg.create_pool", mock_create_pool),
        patch("ragnexus.composition.PgVectorStore", return_value=store_inner),
        patch("ragnexus.composition.get_settings", return_value=cfg),
        patch("ragnexus.composition.setup_logging", return_value=log_listener),
        patch("ragnexus.composition.OpenAICompatEmbedder", return_value=mock_embedder),
        patch("ragnexus.composition.OpenAICompatibleLLMProvider", return_value=mock_llm),
        patch("ragnexus.composition.PgKnowledgeBaseRepository", return_value=mock_kb_repo),
        patch("ragnexus.composition.PgRetrieveLogRepository", return_value=mock_log_repo),
        patch("ragnexus.composition.asyncio.create_task", side_effect=_fake_create_task),
    ):
        yield cfg


def _run_lifespan_state(state_attr: str, cfg_overrides: dict[str, Any] | None = None) -> Any:
    """运行 lifespan 并返回 app.state.<state_attr>，或 None（如果未设置）。"""
    from fastapi import FastAPI

    from ragnexus.composition import lifespan as real_lifespan

    with _patched_lifespan(cfg_overrides):
        captured: dict[str, Any] = {}

        @asynccontextmanager
        async def _wrap(app: FastAPI):
            async with real_lifespan(app):
                captured[state_attr] = getattr(app.state, state_attr, None)
                yield

        app = FastAPI(lifespan=_wrap)
        asyncio.run(app.router.lifespan_context(app).__aenter__())
        return captured.get(state_attr)


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

    def test_repo_pool_is_wrapped_with_loggedpool(self):
        """lifespan 启动后，app.state.repo_pool 应为 LoggedPool 实例。"""
        repo_pool = _run_lifespan_state("repo_pool")
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

    def test_rerank_disabled_uses_noop_reranker(self):
        """RERANK_ENABLED=False 时，retrieve_uc 的 reranker 为 NoopRerankProvider 实例。"""
        from ragnexus.adapters.rerank.noop import NoopRerankProvider

        retrieve_uc = _run_lifespan_state("retrieve_uc", {"RERANK_ENABLED": False})
        assert retrieve_uc is not None, "lifespan 应设置 app.state.retrieve_uc"
        assert isinstance(
            retrieve_uc._reranker, NoopRerankProvider
        ), f"禁用重排时应为 NoopRerankProvider，实际: {type(retrieve_uc._reranker).__name__}"
        assert retrieve_uc._candidate_multiplier == 1, "禁用重排时 candidate_multiplier 应为 1"
        assert retrieve_uc._min_candidates == 0, "禁用重排时 min_candidates 应为 0"


# ============================================================================
# TestCacheInvalidatingUploadUseCase — 上传后清空 rerank + rewrite 缓存
# ============================================================================


class TestCacheInvalidatingUploadUseCase:
    """验证 CacheInvalidatingUploadUseCase.execute 上传成功后清空双缓存。

    纯单元测试 — 不走 lifespan。直接构造包装类，验证副作用调用。
    """

    def _make_inner(self) -> AsyncMock:
        inner = AsyncMock()
        inner.execute.return_value = UploadResult(
            doc_id="d-1", kb_id="kb-1", chunks=[], chunk_count=0
        )
        return inner

    def test_clears_rerank_and_rewrite_cache_after_upload(self):
        """execute() 成功后必须调用 reranker.clear_cache(kb_id) 和 rewriter.clear_cache(kb_id)。"""
        from ragnexus.composition import CacheInvalidatingUploadUseCase

        inner = self._make_inner()
        reranker = AsyncMock()
        rewriter = AsyncMock()

        uc = CacheInvalidatingUploadUseCase(inner, reranker, rewriter)
        asyncio.run(
            uc.execute(
                kb_id="kb-1",
                file_content=b"hello",
                filename="f.txt",
                content_type="text/plain",
            )
        )

        inner.execute.assert_awaited_once_with(
            kb_id="kb-1",
            file_content=b"hello",
            filename="f.txt",
            content_type="text/plain",
        )
        reranker.clear_cache.assert_awaited_once_with("kb-1")
        rewriter.clear_cache.assert_awaited_once_with("kb-1")

    def test_does_not_clear_cache_when_inner_upload_fails(self):
        """inner.execute 抛异常时，不应清空缓存。"""
        from ragnexus.composition import CacheInvalidatingUploadUseCase

        inner = AsyncMock()
        inner.execute.side_effect = RuntimeError("upload failed")
        reranker = AsyncMock()
        rewriter = AsyncMock()

        uc = CacheInvalidatingUploadUseCase(inner, reranker, rewriter)
        with pytest.raises(RuntimeError, match="upload failed"):
            asyncio.run(
                uc.execute(
                    kb_id="kb-1",
                    file_content=b"x",
                    filename="f.txt",
                    content_type="text/plain",
                )
            )

        reranker.clear_cache.assert_not_called()
        rewriter.clear_cache.assert_not_called()
