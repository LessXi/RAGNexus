"""POST /v1/rag/feedback 路由测试 — 正常提交 + 错误场景全覆盖。"""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ragnexus.adapters.http.error_handlers import register_error_handlers
from ragnexus.adapters.http.feedback_router import create_router
from ragnexus.core.auth import TenantContext
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.schemas.feedback import FeedbackData

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_feedback_service():
    """返回 mock FeedbackService，submit_feedback 默认正常返回。"""
    svc = AsyncMock()
    svc.submit_feedback.return_value = FeedbackData(
        feedback_id="score_abc123",
        trace_id="trace_xyz",
        log_id="log_001",
        score=5,
    )
    return svc


@pytest.fixture
def app(mock_feedback_service):
    """构造含 feedback router 和 error_handler 的测试 FastAPI 应用。"""

    async def mock_get_current_tenant():
        return TenantContext(
            tenant_id="default",
            tenant_name="默认租户",
            key_id="test",
            key_prefix="test",
            plan="standard",
        )

    app = FastAPI()
    app.include_router(create_router(mock_get_current_tenant, mock_feedback_service))
    register_error_handlers(app)
    return app


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ── 正常场景 ────────────────────────────────────────────────────────────────


class TestSubmitFeedbackNormal:
    """正常提交流程 — 返回 feedback_id。"""

    def test_returns_feedback_data(self, client, mock_feedback_service):
        resp = client.post(
            "/v1/rag/feedback",
            json={
                "trace_id": "trace_xyz",
                "log_id": "log_001",
                "score": 5,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["feedback_id"] == "score_abc123"
        assert data["trace_id"] == "trace_xyz"
        assert data["log_id"] == "log_001"
        assert data["score"] == 5
        mock_feedback_service.submit_feedback.assert_awaited_once()

    def test_minimal_request_no_log_id(self, client, mock_feedback_service):
        """不传 log_id 也应正常处理。"""
        mock_feedback_service.submit_feedback.return_value = FeedbackData(
            feedback_id="score_xyz",
            trace_id="trace_xyz",
            log_id=None,
            score=3,
        )
        resp = client.post(
            "/v1/rag/feedback",
            json={"trace_id": "trace_xyz", "score": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["log_id"] is None
        assert data["score"] == 3


# ── 评分越界 ────────────────────────────────────────────────────────────────


class TestSubmitFeedbackInvalidScore:
    """评分越界 — Pydantic 验证直接拦截（ge=1, le=5），返回 PARAM_ERROR。
    服务层的防御性 FEEDBACK_INVALID_SCORE 也独立测试。
    """

    def test_score_below_1_pydantic(self, client, mock_feedback_service):
        """Pydantic ge=1 拦截 score=0。"""
        resp = client.post(
            "/v1/rag/feedback",
            json={"trace_id": "trace_xyz", "score": 0},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["code"] == ErrorCode.PARAM_ERROR.code
        mock_feedback_service.submit_feedback.assert_not_called()

    def test_score_above_5_pydantic(self, client, mock_feedback_service):
        """Pydantic le=5 拦截 score=6。"""
        resp = client.post(
            "/v1/rag/feedback",
            json={"trace_id": "trace_xyz", "score": 6},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["code"] == ErrorCode.PARAM_ERROR.code
        mock_feedback_service.submit_feedback.assert_not_called()

    def test_service_layer_invalid_score(self, client, mock_feedback_service):
        """服务层防御性检查抛 FEEDBACK_INVALID_SCORE (20022)。"""
        mock_feedback_service.submit_feedback.side_effect = AppError(
            ErrorCode.FEEDBACK_INVALID_SCORE,
        )
        resp = client.post(
            "/v1/rag/feedback",
            json={"trace_id": "trace_xyz", "score": 3},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["code"] == ErrorCode.FEEDBACK_INVALID_SCORE.code


# ── 无权操作 ────────────────────────────────────────────────────────────────


class TestSubmitFeedbackUnauthorized:
    """无权操作 → 403 (FEEDBACK_UNAUTHORIZED)。"""

    def test_log_not_found(self, client, mock_feedback_service):
        mock_feedback_service.submit_feedback.side_effect = AppError(
            ErrorCode.FEEDBACK_UNAUTHORIZED,
            "未找到对应的检索日志",
        )
        resp = client.post(
            "/v1/rag/feedback",
            json={
                "trace_id": "trace_xyz",
                "log_id": "nonexistent",
                "score": 4,
            },
        )
        assert resp.status_code == 403
        data = resp.json()
        assert data["code"] == ErrorCode.FEEDBACK_UNAUTHORIZED.code

    def test_tenant_mismatch(self, client, mock_feedback_service):
        mock_feedback_service.submit_feedback.side_effect = AppError(
            ErrorCode.FEEDBACK_UNAUTHORIZED,
            "租户无权操作该反馈记录",
        )
        resp = client.post(
            "/v1/rag/feedback",
            json={
                "trace_id": "trace_xyz",
                "log_id": "log_001",
                "score": 4,
            },
        )
        assert resp.status_code == 403
        data = resp.json()
        assert data["code"] == ErrorCode.FEEDBACK_UNAUTHORIZED.code

    def test_trace_id_mismatch(self, client, mock_feedback_service):
        mock_feedback_service.submit_feedback.side_effect = AppError(
            ErrorCode.FEEDBACK_UNAUTHORIZED,
            "trace_id 与日志记录不一致",
        )
        resp = client.post(
            "/v1/rag/feedback",
            json={
                "trace_id": "wrong_trace",
                "log_id": "log_001",
                "score": 4,
            },
        )
        assert resp.status_code == 403
        data = resp.json()
        assert data["code"] == ErrorCode.FEEDBACK_UNAUTHORIZED.code


# ── 服务不可用 ──────────────────────────────────────────────────────────────


class TestSubmitFeedbackServiceUnavailable:
    """Langfuse 不可用 → 503 (FEEDBACK_SERVICE_UNAVAILABLE)。"""

    def test_langfuse_disabled(self, client, mock_feedback_service):
        mock_feedback_service.submit_feedback.side_effect = AppError(
            ErrorCode.FEEDBACK_SERVICE_UNAVAILABLE,
        )
        resp = client.post(
            "/v1/rag/feedback",
            json={
                "trace_id": "trace_xyz",
                "log_id": "log_001",
                "score": 5,
            },
        )
        assert resp.status_code == 503
        data = resp.json()
        assert data["code"] == ErrorCode.FEEDBACK_SERVICE_UNAVAILABLE.code


# ── 请求体校验 ──────────────────────────────────────────────────────────────


class TestSubmitFeedbackValidation:
    """请求体校验 → 422 (Pydantic / PARAM_ERROR)。"""

    def test_missing_trace_id(self, client):
        resp = client.post(
            "/v1/rag/feedback",
            json={"score": 3},
        )
        assert resp.status_code == 422

    def test_missing_score(self, client):
        resp = client.post(
            "/v1/rag/feedback",
            json={"trace_id": "trace_xyz"},
        )
        assert resp.status_code == 422

    def test_score_not_integer(self, client):
        resp = client.post(
            "/v1/rag/feedback",
            json={"trace_id": "trace_xyz", "score": "great"},
        )
        assert resp.status_code == 422

    def test_extra_fields_ignored(self, client, mock_feedback_service):
        """FeedbackRequest 配置 extra="ignore"，多余字段应被忽略。"""
        resp = client.post(
            "/v1/rag/feedback",
            json={
                "trace_id": "trace_xyz",
                "score": 5,
                "foo": "bar",
            },
        )
        assert resp.status_code == 200
