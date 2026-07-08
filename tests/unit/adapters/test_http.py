"""Tests for HTTP routers (create_kb, upload_doc, retrieve) and error handlers."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ragnexus.adapters.http.create_kb_router import create_router as create_kb_router
from ragnexus.adapters.http.error_handlers import register_error_handlers
from ragnexus.adapters.http.retrieve_router import (
    create_router as create_retrieve_router,
)
from ragnexus.adapters.http.upload_doc_router import (
    create_router as create_upload_router,
)
from ragnexus.core.auth import TenantContext
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import (
    DocStatus,
    KnowledgeBase,
    RetrieveResult,
    SearchHit,
    UploadResult,
)
from ragnexus.observability import RetrieveObservability

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_kb_uc():
    return AsyncMock()


@pytest.fixture
def mock_upload_uc():
    return AsyncMock()


@pytest.fixture
def mock_retrieve_uc():
    return AsyncMock()


@pytest.fixture
def app(mock_kb_uc, mock_upload_uc, mock_retrieve_uc):
    async def mock_get_current_tenant():
        return TenantContext(
            tenant_id="default",
            tenant_name="默认租户",
            key_id="test",
            key_prefix="test",
            plan="standard",
        )

    app = FastAPI()
    app.include_router(create_kb_router(mock_kb_uc, mock_get_current_tenant))
    app.include_router(create_upload_router(mock_upload_uc, mock_get_current_tenant))
    app.include_router(
        create_retrieve_router(mock_retrieve_uc, mock_get_current_tenant)
    )
    app.state.langfuse_client = RetrieveObservability(enabled=False)
    register_error_handlers(app)
    return app


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def free_plan_app(mock_retrieve_uc):
    """Free 套餐 app — max_kb_per_retrieve=1"""

    async def mock_get_current_tenant():
        return TenantContext(
            tenant_id="default",
            tenant_name="默认租户",
            key_id="test",
            key_prefix="test",
            plan="free",
        )

    app = FastAPI()
    app.include_router(
        create_retrieve_router(mock_retrieve_uc, mock_get_current_tenant)
    )
    app.state.langfuse_client = RetrieveObservability(enabled=False)
    register_error_handlers(app)
    return app


@pytest.fixture
def free_plan_client(free_plan_app):
    return TestClient(free_plan_app, raise_server_exceptions=False)


# ── Create KB ─────────────────────────────────────────────────────────────


class TestCreateKB:
    """POST /v1/knowledge-bases:create"""

    def test_success(self, client, mock_kb_uc):
        mock_kb_uc.execute.return_value = KnowledgeBase(
            id="kb_test123",
            name="Test KB",
            created_at=datetime(2026, 6, 22, 10, 0, 0),
            tenant_id="default",
        )
        resp = client.post(
            "/v1/knowledge-bases:create",
            json={"name": "Test KB", "tenant_id": "default"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["kb_id"] == "kb_test123"
        assert data["data"]["name"] == "Test KB"
        assert data["data"]["tenant_id"] == "default"
        assert data["data"]["created_at"] == "2026-06-22T10:00:00"
        assert data["message"] == "ok"

    def test_validation(self, client, mock_kb_uc):
        """name too short / too long / missing → 422"""
        # empty → pydantic min_length=1
        resp = client.post(
            "/v1/knowledge-bases:create", json={"name": "", "tenant_id": "test"}
        )
        assert resp.status_code == 422

        # too long → pydantic max_length=64
        resp = client.post(
            "/v1/knowledge-bases:create", json={"name": "A" * 65, "tenant_id": "test"}
        )
        assert resp.status_code == 422

        # missing name field
        resp = client.post("/v1/knowledge-bases:create", json={"tenant_id": "test"})
        assert resp.status_code == 422


# ── Upload Doc ────────────────────────────────────────────────────────────


class TestUploadDoc:
    """POST /v1/documents:upload"""

    def test_success(self, client, mock_upload_uc):
        mock_upload_uc.execute.return_value = UploadResult(
            doc_id="doc_hash12345678",
            kb_id="kb_test123",
            status=DocStatus.PROCESSING,
            chunks=[],
        )
        resp = client.post(
            "/v1/documents:upload",
            data={"kb_id": "kb_test123"},
            files={"file": ("test.md", b"# Hello\nWorld", "text/markdown")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["doc_id"] == "doc_hash12345678"
        assert data["data"]["kb_id"] == "kb_test123"
        assert data["data"]["chunk_count"] == 0
        assert data["message"] == "ok"

    def test_wrong_extension(self, client, mock_upload_uc):
        mock_upload_uc.execute.side_effect = AppError(
            ErrorCode.UNSUPPORTED_FORMAT,
            "不支持的文件类型: .pdf",
        )
        resp = client.post(
            "/v1/documents:upload",
            data={"kb_id": "kb_test123"},
            files={"file": ("test.pdf", b"%PDF-1.4...", "application/pdf")},
        )
        assert resp.status_code == 415
        data = resp.json()
        assert data["code"] == ErrorCode.UNSUPPORTED_FORMAT.code
        assert data["data"] is None
        assert "不支持的文件类型" in data["message"]


# ── Retrieve ──────────────────────────────────────────────────────────────


class TestRetrieve:
    """POST /v1/rag:retrieve"""

    def test_success(self, client, mock_retrieve_uc):
        from ragnexus.domain.models import RetrieveResult

        mock_retrieve_uc.execute.return_value = RetrieveResult(
            hits=[
                SearchHit(
                    chunk_id="doc_hash:0",
                    kb_id="kb_test123",
                    doc_id="doc_hash",
                    score=0.823456,
                    text="chunk content",
                    metadata={},
                )
            ],
            total=1,
            latency_ms=42,
            mode="hybrid",
            vector_count=0,
            bm25_count=0,
            fused_count=1,
            rerank_model=None,
            degraded=False,
            degraded_reason=None,
        )
        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "test query",
                "kb_ids": ["kb_test123"],
                "top_k": 5,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["meta"]["total"] == 1
        assert data["data"]["hits"][0]["chunk_id"] == "doc_hash:0"
        assert data["data"]["hits"][0]["score"] == 0.823456
        assert data["message"] == "ok"

    def test_router_rejects_exceeded_kb_limit(self, free_plan_client, mock_retrieve_uc):
        """free 套餐 (max_kb_per_retrieve=1) 传 2 库 → 20013 FEATURE_NOT_ALLOWED"""
        resp = free_plan_client.post(
            "/v1/rag:retrieve",
            json={
                "query": "test query",
                "kb_ids": ["kb_1", "kb_2"],
                "top_k": 5,
            },
        )
        assert resp.status_code == 403
        data = resp.json()
        assert data["code"] == 20013
        mock_retrieve_uc.execute.assert_not_called()

    def test_response_includes_kb_ids(self, client, mock_retrieve_uc):
        """响应 data 中应包含 kb_ids 字段"""
        from ragnexus.domain.models import RetrieveResult

        mock_retrieve_uc.execute.return_value = RetrieveResult(
            hits=[],
            total=0,
            latency_ms=42,
            mode="hybrid",
            vector_count=0,
            bm25_count=0,
            fused_count=0,
            rerank_model=None,
            degraded=False,
            degraded_reason=None,
        )
        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "test query",
                "kb_ids": ["kb_a", "kb_b"],
                "top_k": 5,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["kb_ids"] == ["kb_a", "kb_b"]
        # 验证 meta 中多库元信息
        meta = data["data"]["meta"]
        assert meta["multi_kb"] is True
        assert meta["kb_count"] == 2
        assert meta["fusion"] == "rrf"
        assert meta["rrf_k"] == 60
        assert "per_kb_top_k" in meta

    def test_serialize_hit_has_kb_name(self, client, mock_retrieve_uc):
        """_serialize_hit 输出应包含 kb_name 字段"""
        from ragnexus.domain.models import RetrieveResult

        mock_retrieve_uc.execute.return_value = RetrieveResult(
            hits=[
                SearchHit(
                    chunk_id="doc_hash:0",
                    kb_id="kb_test123",
                    doc_id="doc_hash",
                    score=0.823456,
                    text="chunk content",
                    metadata={},
                    kb_name="测试知识库",
                )
            ],
            total=1,
            latency_ms=42,
            mode="hybrid",
            vector_count=0,
            bm25_count=0,
            fused_count=1,
            rerank_model=None,
            degraded=False,
            degraded_reason=None,
        )
        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "test query",
                "kb_ids": ["kb_test123"],
                "top_k": 5,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["hits"][0]["kb_name"] == "测试知识库"

    def test_extra_field(self, client, mock_retrieve_uc):
        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "test",
                "kb_ids": ["kb_test123"],
                "top_k": 5,
                "extra": "should not be allowed",
            },
        )
        assert resp.status_code == 422

    def test_profile_rejected_by_plan(self, client, mock_retrieve_uc):
        """profile="quality" 在 free 套餐下应被拒（20013 FEATURE_NOT_ALLOWED）。"""
        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "test query",
                "kb_ids": ["kb_test123"],
                "top_k": 5,
                "profile": "quality",
            },
        )
        assert resp.status_code == 403
        data = resp.json()
        assert data["code"] == 20013
        mock_retrieve_uc.execute.assert_not_called()


class TestRetrieveLangfuse:
    """Langfuse trace 集成 — fire-and-forget 可观测。"""

    def test_disabled_retrieve_succeeds(self, client, app, mock_retrieve_uc):
        """LANGFUSE_ENABLED=false → 正常检索，无 Langfuse 交互。"""
        app.state.langfuse_client = RetrieveObservability(enabled=False)
        mock_retrieve_uc.execute.return_value = RetrieveResult(
            hits=[
                SearchHit(
                    chunk_id="doc_hash:0",
                    kb_id="kb_test123",
                    doc_id="doc_hash",
                    score=0.823456,
                    text="chunk content",
                    metadata={},
                )
            ],
            total=1,
            latency_ms=42,
            mode="hybrid",
            vector_count=0,
            bm25_count=0,
            fused_count=1,
            rerank_model=None,
            degraded=False,
            degraded_reason=None,
        )
        resp = client.post(
            "/v1/rag:retrieve",
            json={"query": "test query", "kb_ids": ["kb_test123"], "top_k": 5},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_enabled_trace_created(self, client, app, mock_retrieve_uc):
        """LANGFUSE_ENABLED=true → create_trace 被调用，metadata 正确。"""
        mock_client = MagicMock(spec=RetrieveObservability)
        mock_client.create_trace.return_value = {"id": "trace-1", "trace": MagicMock()}
        mock_client.create_span.return_value = {"id": "span-1", "span": MagicMock()}
        app.state.langfuse_client = mock_client

        mock_retrieve_uc.execute.return_value = RetrieveResult(
            hits=[
                SearchHit(
                    chunk_id="doc_hash:0",
                    kb_id="kb_test123",
                    doc_id="doc_hash",
                    score=0.823456,
                    text="chunk content",
                    metadata={},
                )
            ],
            total=1,
            latency_ms=42,
            mode="hybrid",
            vector_count=0,
            bm25_count=0,
            fused_count=1,
            rerank_model=None,
            degraded=False,
            degraded_reason=None,
        )
        resp = client.post(
            "/v1/rag:retrieve",
            json={"query": "test query", "kb_ids": ["kb_test123"], "top_k": 5},
        )
        assert resp.status_code == 200

        mock_client.create_trace.assert_called_once_with(
            name="rag_retrieve",
            metadata={
                "tenant_id": "default",
                "kb_ids": ["kb_test123"],
                "profile": "balanced",
                "plan": "standard",
                "search_query": "test query",
            },
        )
        assert mock_client.create_span.call_count == 3
        mock_client.end_trace.assert_called_once()


# ── Error Handler ─────────────────────────────────────────────────────────


class TestErrorHandler:
    """DomainError → proper JSON error response"""

    def test_domain_error_response(self, client, mock_kb_uc):
        mock_kb_uc.execute.side_effect = AppError(
            ErrorCode.SERVER_ERROR,
            "测试错误",
            errors=[{"field": "test", "reason": "测试"}],
        )
        resp = client.post(
            "/v1/knowledge-bases:create", json={"name": "Test", "tenant_id": "test"}
        )
        assert resp.status_code == 500
        data = resp.json()
        assert data["code"] == ErrorCode.SERVER_ERROR.code
        assert data["data"] is None
        assert data["message"] == "测试错误"
        assert data["errors"] == [{"field": "test", "reason": "测试"}]

    def test_validation_error_envelope(self, client):
        """Pydantic validation error → unified error envelope with 422."""
        resp = client.post(
            "/v1/knowledge-bases:create",
            json={"name": "", "tenant_id": "test"},  # min_length=1 on name
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["code"] == ErrorCode.PARAM_ERROR.code
        assert data["data"] is None
        assert data["message"] == "参数错误"
        assert "errors" in data
        assert len(data["errors"]) > 0
        assert all("field" in e and "reason" in e for e in data["errors"])


# ── Catch-All Error Handler ──────────────────────────────────────────────


class TestCatchAllHandler:
    """Unexpected exceptions → 500 + SYSTEM_ERROR log"""

    def test_unexpected_exception_returns_500(self, client, mock_kb_uc):
        """Generic Exception (not AppError) → 500 with SERVER_ERROR code."""
        mock_kb_uc.execute.side_effect = Exception("boom!")

        resp = client.post(
            "/v1/knowledge-bases:create", json={"name": "Test", "tenant_id": "test"}
        )

        assert resp.status_code == 500
        data = resp.json()
        assert data["code"] == ErrorCode.SERVER_ERROR.code
        assert data["message"] == ErrorCode.SERVER_ERROR.msg
        assert data["errors"] == []

    def test_app_error_not_intercepted_by_catchall(self, client, mock_kb_uc):
        """AppError should still be handled by the domain error handler, not catch-all."""
        mock_kb_uc.execute.side_effect = AppError(
            ErrorCode.NOT_FOUND,
            "知识库不存在",
        )

        resp = client.post(
            "/v1/knowledge-bases:create", json={"name": "Test", "tenant_id": "test"}
        )

        # AppError handler returns the code from the AppError, not SERVER_ERROR
        assert resp.status_code == 404
        data = resp.json()
        assert data["code"] == ErrorCode.NOT_FOUND.code
        assert data["message"] == "知识库不存在"

    def test_system_error_log_emitted(self, client, mock_kb_uc):
        """Catch-all handler emits SYSTEM_ERROR log via logger.error."""
        import logging

        mock_kb_uc.execute.side_effect = ValueError("something broke")

        # 收集 ragnexus logger 的 ERROR 级别日志
        rag_logger = logging.getLogger("ragnexus")
        rag_logger.setLevel(logging.DEBUG)
        records: list[logging.LogRecord] = []
        handler = logging.Handler()

        # Monkey-patch emit 来捕获日志（pyright strict 下不可用 lambda）
        def _capture(self, record):
            records.append(record)

        handler.emit = _capture.__get__(handler, logging.Handler)  # type: ignore[method-assign]
        rag_logger.addHandler(handler)

        try:
            client.post(
                "/v1/knowledge-bases:create", json={"name": "Test", "tenant_id": "test"}
            )

            # 应该至少有 1 条 ERROR 日志，其中包含 SYSTEM_ERROR
            system_errors = [
                r for r in records if getattr(r, "event_type", "") == "SYSTEM_ERROR"
            ]
            assert len(system_errors) >= 1
            assert getattr(system_errors[0], "error_type", "") == "ValueError"
            assert "something broke" in str(
                getattr(system_errors[0], "error_message", "")
            )
            assert hasattr(system_errors[0], "traceback")
        finally:
            rag_logger.removeHandler(handler)


# ── Quota Checks ──────────────────────────────────────────────────────────────


class TestQuotaCreateKB:
    """POST /v1/knowledge-bases:create 前走 check_kb_count"""

    def test_quota_svc_called(self):
        """quota_svc 不为 None 时应在 create_kb uc.execute 之前被调用。"""
        from ragnexus.adapters.http.create_kb_router import (
            create_router as create_kb_router,
        )

        mock_uc = AsyncMock()
        mock_uc.execute.return_value = KnowledgeBase(
            id="kb_test123",
            name="Test KB",
            created_at=datetime(2026, 6, 22, 10, 0, 0),
            tenant_id="default",
        )
        mock_quota_svc = AsyncMock()

        async def get_current_tenant():
            return TenantContext(
                tenant_id="default",
                tenant_name="默认租户",
                key_id="test",
                key_prefix="test",
                plan="standard",
            )

        app = FastAPI()
        app.include_router(
            create_kb_router(mock_uc, get_current_tenant, quota_svc=mock_quota_svc)
        )
        register_error_handlers(app)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/v1/knowledge-bases:create",
            json={"name": "Test KB", "tenant_id": "default"},
        )
        assert resp.status_code == 200
        mock_quota_svc.check_kb_count.assert_awaited_once_with("default", "standard")
        mock_uc.execute.assert_awaited_once()

    def test_no_quota_svc_passes_through(self):
        """quota_svc 为 None（默认）时创建正常进行，不抛异常。"""
        from ragnexus.adapters.http.create_kb_router import (
            create_router as create_kb_router,
        )

        mock_uc = AsyncMock()
        mock_uc.execute.return_value = KnowledgeBase(
            id="kb_test123",
            name="Test KB",
            created_at=datetime(2026, 6, 22, 10, 0, 0),
            tenant_id="default",
        )

        async def get_current_tenant():
            return TenantContext(
                tenant_id="default",
                tenant_name="默认租户",
                key_id="test",
                key_prefix="test",
                plan="standard",
            )

        app = FastAPI()
        app.include_router(create_kb_router(mock_uc, get_current_tenant))
        register_error_handlers(app)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/v1/knowledge-bases:create",
            json={"name": "Test KB", "tenant_id": "default"},
        )
        assert resp.status_code == 200


class TestQuotaUploadDoc:
    """POST /v1/documents:upload 前走 check_doc_upload"""

    def test_quota_svc_called(self):
        """quota_svc 不为 None 时应在 upload_doc uc.execute 之前被调用。"""
        from ragnexus.adapters.http.upload_doc_router import (
            create_router as create_upload_router,
        )

        mock_uc = AsyncMock()
        mock_uc.execute.return_value = UploadResult(
            doc_id="doc_hash12345678",
            kb_id="kb_test123",
            status=DocStatus.PROCESSING,
            chunks=[],
        )
        mock_quota_svc = AsyncMock()

        async def get_current_tenant():
            return TenantContext(
                tenant_id="default",
                tenant_name="默认租户",
                key_id="test",
                key_prefix="test",
                plan="standard",
            )

        app = FastAPI()
        app.include_router(
            create_upload_router(mock_uc, get_current_tenant, quota_svc=mock_quota_svc)
        )
        register_error_handlers(app)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/v1/documents:upload",
            data={"kb_id": "kb_test123"},
            files={"file": ("test.md", b"# Hello\nWorld", "text/markdown")},
        )
        assert resp.status_code == 201
        mock_quota_svc.check_doc_upload.assert_awaited_once_with(
            "kb_test123", "default", "standard"
        )
        mock_uc.execute.assert_awaited_once()


class TestQuotaDocumentReindex:
    """POST /v1/documents/{doc_id}/reindex 前走 check_processing"""

    def test_quota_svc_called(self):
        """quota_svc 不为 None 时应在 reindex uc.execute 之前被调用。"""
        from ragnexus.adapters.http.document_router import create_document_router

        mock_query_uc = AsyncMock()
        mock_delete_uc = AsyncMock()
        mock_reindex_uc = AsyncMock()
        mock_reindex_uc.execute.return_value = {"status": "processing"}
        mock_quota_svc = AsyncMock()

        async def get_current_tenant():
            return TenantContext(
                tenant_id="default",
                tenant_name="默认租户",
                key_id="test",
                key_prefix="test",
                plan="standard",
            )

        app = FastAPI()
        app.include_router(
            create_document_router(
                mock_query_uc,
                mock_delete_uc,
                mock_reindex_uc,
                get_current_tenant,
                quota_svc=mock_quota_svc,
            )
        )
        register_error_handlers(app)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post("/v1/documents/doc_abc/reindex")
        assert resp.status_code == 200
        mock_quota_svc.check_processing.assert_awaited_once_with("default", "standard")
        mock_reindex_uc.execute.assert_awaited_once()
