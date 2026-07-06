"""Tests for /v1/auth/me — response schema with plan, features, limits, usage."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ragnexus.adapters.http.auth_router import create_auth_router
from ragnexus.core.auth import TenantContext


@pytest.fixture
def mock_get_current_tenant():
    async def _fn():
        return TenantContext(
            tenant_id="t1",
            tenant_name="Test",
            key_id="k1",
            key_prefix="rk_abcd",
            plan="standard",
        )

    return _fn


# ── RED: 验证新字段存在 ────────────────────────────────────────────────


class TestAuthMeResponseSchema:
    """GET /v1/auth/me 返回 plan、features、limits、usage 字段。"""

    @pytest.fixture
    def client(self, mock_get_current_tenant):
        app = FastAPI()
        app.include_router(create_auth_router(mock_get_current_tenant))
        return TestClient(app, raise_server_exceptions=False)

    def test_response_contains_plan_field(self, client):
        """响应中必须包含 plan 字段。"""
        resp = client.get("/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan"] == "standard"

    def test_response_contains_features(self, client):
        """响应中必须包含 features 字典。"""
        resp = client.get("/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert "features" in data
        assert isinstance(data["features"], dict)
        # standard plan features
        assert data["features"]["hybrid_allowed"] is True
        assert data["features"]["rerank_allowed"] is False

    def test_response_contains_limits(self, client):
        """响应中必须包含 limits 字典。"""
        resp = client.get("/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert "limits" in data
        assert isinstance(data["limits"], dict)
        assert data["limits"]["retrieve_qps"] == 10
        assert data["limits"]["max_kb"] == 5

    def test_response_contains_usage(self, client):
        """响应中必须包含 usage 字典（无 repo/limiter 时为 0）。"""
        resp = client.get("/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert "usage" in data
        assert isinstance(data["usage"], dict)
        assert data["usage"]["kb_count"] == 0
        assert data["usage"]["retrieve_daily_count"] == 0

    def test_legacy_fields_still_present(self, client):
        """原有的 tenant_id、tenant_name、key_id、key_prefix 仍保留。"""
        resp = client.get("/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "t1"
        assert data["tenant_name"] == "Test"
        assert data["key_id"] == "k1"
        assert data["key_prefix"] == "rk_abcd"


# ── GREEN: 带 mock repo/limiter 的扩展测试 ──────────────────────────────


class TestAuthMeWithDependencies:
    """使用 tenant_repo 和 rate_limiter 时，usage 字段正确填充。"""

    @pytest.fixture
    def client_with_deps(self, mock_get_current_tenant):
        tenant_repo = AsyncMock()
        tenant_repo.pool = AsyncMock()
        tenant_repo.pool.fetchval = AsyncMock(return_value=3)

        rate_limiter = AsyncMock()
        rate_limiter.get_daily_count = AsyncMock(return_value=42)

        app = FastAPI()
        app.include_router(create_auth_router(mock_get_current_tenant, tenant_repo, rate_limiter))
        return TestClient(app, raise_server_exceptions=False)

    def test_usage_kb_count_from_repo(self, client_with_deps):
        """kb_count 从 tenant_repo 查询。"""
        resp = client_with_deps.get("/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["usage"]["kb_count"] == 3

    def test_usage_daily_count_from_limiter(self, client_with_deps):
        """retrieve_daily_count 从 rate_limiter 查询。"""
        resp = client_with_deps.get("/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["usage"]["retrieve_daily_count"] == 42


# ── EDGE: free plan ─────────────────────────────────────────────────────


class TestAuthMeFreePlan:
    """free plan 的 features/limits 正确返回。"""

    @pytest.fixture
    def client_free(self):
        async def get_tenant():
            return TenantContext(
                tenant_id="t2",
                tenant_name="FreeUser",
                key_id="k2",
                key_prefix="rk_free",
                plan="free",
            )

        app = FastAPI()
        app.include_router(create_auth_router(get_tenant))
        return TestClient(app, raise_server_exceptions=False)

    def test_free_plan_limits(self, client_free):
        resp = client_free.get("/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["limits"]["max_kb"] == 1
        assert data["limits"]["retrieve_daily"] == 500
        assert data["features"]["hybrid_allowed"] is False

    def test_free_plan_features(self, client_free):
        resp = client_free.get("/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["features"]["allowed_profiles"] == ["speed"]


# ── EDGE: pro plan ──────────────────────────────────────────────────────


class TestAuthMeProPlan:
    """pro plan 的 features/limits 正确返回。"""

    @pytest.fixture
    def client_pro(self):
        async def get_tenant():
            return TenantContext(
                tenant_id="t3",
                tenant_name="ProUser",
                key_id="k3",
                key_prefix="rk_pro",
                plan="pro",
            )

        app = FastAPI()
        app.include_router(create_auth_router(get_tenant))
        return TestClient(app, raise_server_exceptions=False)

    def test_pro_plan_limits(self, client_pro):
        resp = client_pro.get("/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["limits"]["max_kb"] == 50
        assert data["limits"]["retrieve_daily"] == 100000
        assert data["limits"]["max_processing_documents"] == 10

    def test_pro_plan_features(self, client_pro):
        resp = client_pro.get("/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["features"]["rerank_allowed"] is True
        assert data["features"]["query_rewrite_allowed"] is True
