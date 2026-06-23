"""E2E smoke tests — real FastAPI app against test-db (Docker Compose).

Required:
- Docker Compose (test-db on port 5433)
- Optional: EMBED_API_KEY for upload & retrieve success tests
"""

import os
import subprocess

import pytest
from config import get_settings

pytestmark = [
    pytest.mark.e2e,
]


# ── helpers ────────────────────────────────────────────────────────────


def _embedder_available() -> bool:
    """Check if a real embedder endpoint is available (API key set)."""
    return bool(os.environ.get("EMBED_API_KEY") or get_settings().EMBED_API_KEY)


# ── Tests ──────────────────────────────────────────────────────────────


class TestE2ECreateKB:
    """POST /v1/knowledge-bases:create — E2E smoke tests."""

    def test_create_kb_success(self, client):
        resp = client.post(
            "/v1/knowledge-bases:create",
            json={"name": "E2E Smoke KB"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["name"] == "E2E Smoke KB"
        assert data["data"]["kb_id"].startswith("kb_")
        assert "created_at" in data["data"]

    def test_create_duplicate_kb_409(self, client):
        """Same name → 409 Conflict (code 1200)."""
        name = "E2E Duplicate Test"
        client.post("/v1/knowledge-bases:create", json={"name": name})
        resp = client.post("/v1/knowledge-bases:create", json={"name": name})
        assert resp.status_code == 409
        data = resp.json()
        assert data["code"] == 1200
        assert data["data"] is None

    def test_empty_name_422(self, client):
        """Empty/blank name → 422 validation error."""
        resp = client.post(
            "/v1/knowledge-bases:create", json={"name": ""}
        )
        assert resp.status_code == 422

        # Missing name field entirely
        resp = client.post("/v1/knowledge-bases:create", json={})
        assert resp.status_code == 422


class TestE2EUploadErrors:
    """POST /v1/documents:upload — error cases (no embedder needed)."""

    def test_upload_missing_kb_404(self, client):
        """Non-existent kb_id → 404."""
        resp = client.post(
            "/v1/documents:upload",
            data={"kb_id": "kb_nonexistent_e2e"},
            files={"file": ("test.md", b"# Hello\nWorld", "text/markdown")},
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 1100

    def test_upload_wrong_extension_415(self, client):
        """Uploading .pdf → 415."""
        resp = client.post(
            "/v1/documents:upload",
            data={"kb_id": "kb_dummy"},
            files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert resp.status_code == 415
        assert resp.json()["code"] == 1300

    def test_upload_over_max_size_413(self, client):
        """File > 10MB → 413 Payload Too Large."""
        oversized = b"x" * (10 * 1024 * 1024 + 1)
        resp = client.post(
            "/v1/documents:upload",
            data={"kb_id": "kb_dummy"},
            files={"file": ("big.md", oversized, "text/markdown")},
        )
        assert resp.status_code == 413
        assert resp.json()["code"] == 1301


class TestE2ERetrieveErrors:
    """POST /v1/rag:retrieve — error cases (no embedder needed)."""

    def test_retrieve_missing_kb_404(self, client):
        """Non-existent kb_id → 404."""
        resp = client.post(
            "/v1/rag:retrieve",
            json={"query": "test", "kb_ids": ["kb_nonexistent_e2e"], "top_k": 5},
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 1100

    def test_retrieve_extra_field_422(self, client):
        """Extra ``filter`` field (model_config extra=forbid) → 422."""
        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "test",
                "kb_ids": ["kb_dummy"],
                "top_k": 5,
                "filter": {"x": 1},
            },
        )
        assert resp.status_code == 422

    def test_retrieve_empty_query_422(self, client):
        """Empty query string → 422."""
        resp = client.post(
            "/v1/rag:retrieve",
            json={"query": "", "kb_ids": ["kb_dummy"], "top_k": 5},
        )
        assert resp.status_code == 422


class TestE2EFullFlow:
    """Full end-to-end: create KB → upload doc → retrieve.
    Requires a real embedder (EMBED_API_KEY).
    """

    @pytest.fixture(scope="class")
    def embedder_available(self):
        return _embedder_available()

    def test_upload_and_retrieve_success(self, client, embedder_available):
        if not embedder_available:
            pytest.skip("EMBED_API_KEY not set — requires a real embedder")

        # 1. Create KB
        resp = client.post(
            "/v1/knowledge-bases:create",
            json={"name": "E2E Full Flow"},
        )
        assert resp.status_code == 200
        kb_id = resp.json()["data"]["kb_id"]

        # 2. Upload .md file
        content = b"# Hello\n\nThis is an E2E test document for RAGNexus."
        resp = client.post(
            "/v1/documents:upload",
            data={"kb_id": kb_id},
            files={"file": ("e2e-test.md", content, "text/markdown")},
        )
        assert resp.status_code == 201
        upload_data = resp.json()
        assert upload_data["code"] == 0
        assert upload_data["data"]["doc_id"]
        assert upload_data["data"]["kb_id"] == kb_id
        assert upload_data["data"]["chunk_count"] >= 0

        # 3. Retrieve
        resp = client.post(
            "/v1/rag:retrieve",
            json={"query": "RAGNexus", "kb_ids": [kb_id], "top_k": 3},
        )
        assert resp.status_code == 200
        retrieve_data = resp.json()
        assert retrieve_data["code"] == 0
        assert retrieve_data["data"]["total"] >= 0
        assert isinstance(retrieve_data["data"]["hits"], list)
