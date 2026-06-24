"""Tests for HTTP routers (create_kb, upload_doc, retrieve) and error handlers."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ragnexus.adapters.http.create_kb_router import create_router as create_kb_router
from ragnexus.adapters.http.error_handlers import register_error_handlers
from ragnexus.adapters.http.retrieve_router import create_router as create_retrieve_router
from ragnexus.adapters.http.upload_doc_router import create_router as create_upload_router
from ragnexus.domain.errors import DomainError, UnsupportedMediaTypeError
from ragnexus.domain.models import KnowledgeBase, SearchHit, UploadResult

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
    app = FastAPI()
    app.include_router(create_kb_router(mock_kb_uc))
    app.include_router(create_upload_router(mock_upload_uc))
    app.include_router(create_retrieve_router(mock_retrieve_uc))
    register_error_handlers(app)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ── Create KB ─────────────────────────────────────────────────────────────


class TestCreateKB:
    """POST /v1/knowledge-bases:create"""

    def test_success(self, client, mock_kb_uc):
        mock_kb_uc.execute.return_value = KnowledgeBase(
            id="kb_test123",
            name="Test KB",
            created_at=datetime(2026, 6, 22, 10, 0, 0),
        )
        resp = client.post("/v1/knowledge-bases:create", json={"name": "Test KB"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["kb_id"] == "kb_test123"
        assert data["data"]["name"] == "Test KB"
        assert data["data"]["created_at"] == "2026-06-22T10:00:00"
        assert data["message"] == "ok"

    def test_validation(self, client, mock_kb_uc):
        """name too short / too long / missing → 422"""
        # empty → pydantic min_length=1
        resp = client.post("/v1/knowledge-bases:create", json={"name": ""})
        assert resp.status_code == 422

        # too long → pydantic max_length=64
        resp = client.post("/v1/knowledge-bases:create", json={"name": "A" * 65})
        assert resp.status_code == 422

        # missing name field
        resp = client.post("/v1/knowledge-bases:create", json={})
        assert resp.status_code == 422


# ── Upload Doc ────────────────────────────────────────────────────────────


class TestUploadDoc:
    """POST /v1/documents:upload"""

    def test_success(self, client, mock_upload_uc):
        mock_upload_uc.execute.return_value = UploadResult(
            doc_id="doc_hash12345678",
            kb_id="kb_test123",
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
        mock_upload_uc.execute.side_effect = UnsupportedMediaTypeError(
            "不支持的文件类型: .pdf",
            errors=[{"field": "filename", "reason": "仅支持 .md, .txt 格式"}],
        )
        resp = client.post(
            "/v1/documents:upload",
            data={"kb_id": "kb_test123"},
            files={"file": ("test.pdf", b"%PDF-1.4...", "application/pdf")},
        )
        assert resp.status_code == 415
        data = resp.json()
        assert data["code"] == 1300
        assert data["data"] is None
        assert "不支持的文件类型" in data["message"]


# ── Retrieve ──────────────────────────────────────────────────────────────


class TestRetrieve:
    """POST /v1/rag:retrieve"""

    def test_success(self, client, mock_retrieve_uc):
        mock_retrieve_uc.execute.return_value = [
            SearchHit(
                chunk_id="doc_hash:0",
                kb_id="kb_test123",
                doc_id="doc_hash",
                score=0.823456,
                text="chunk content",
                metadata={},
            )
        ]
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
        assert data["data"]["total"] == 1
        assert data["data"]["hits"][0]["chunk_id"] == "doc_hash:0"
        assert data["data"]["hits"][0]["score"] == 0.823456
        assert data["message"] == "ok"

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


# ── Error Handler ─────────────────────────────────────────────────────────


class TestErrorHandler:
    """DomainError → proper JSON error response"""

    def test_domain_error_response(self, client, mock_kb_uc):
        mock_kb_uc.execute.side_effect = DomainError(
            "测试错误",
            errors=[{"field": "test", "reason": "测试"}],
        )
        resp = client.post("/v1/knowledge-bases:create", json={"name": "Test"})
        assert resp.status_code == 500
        data = resp.json()
        assert data["code"] == 9999
        assert data["data"] is None
        assert data["message"] == "测试错误"
        assert data["errors"] == [{"field": "test", "reason": "测试"}]

    def test_validation_error_envelope(self, client):
        """Pydantic validation error → unified error envelope with 422."""
        resp = client.post(
            "/v1/knowledge-bases:create",
            json={"name": ""},  # min_length=1
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["code"] == 1000
        assert data["data"] is None
        assert data["message"] == "参数错误"
        assert "errors" in data
        assert len(data["errors"]) > 0
        assert all("field" in e and "reason" in e for e in data["errors"])
