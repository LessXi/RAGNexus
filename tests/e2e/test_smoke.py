"""E2E smoke tests — real FastAPI app against test-db (Docker Compose).

Required:
- Docker Compose (test-db on port 5433)
- Optional: EMBED_API_KEY for upload & retrieve success tests
"""

import os

import pytest

from ragnexus.config import get_settings
from ragnexus.core.errors import ErrorCode
import asyncio
import asyncpg
import concurrent.futures
import re

from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient


from ragnexus.composition import build_app

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
        name = f"E2E Smoke KB {os.urandom(4).hex()}"
        resp = client.post(
            "/v1/knowledge-bases:create",
            json={"name": name},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["name"] == name
        assert data["data"]["kb_id"].startswith("kb_")
        assert "created_at" in data["data"]

    def test_create_duplicate_kb_409(self, client):
        """Same name → 409 Conflict (code 10301)."""
        name = f"E2E Duplicate Test {os.urandom(4).hex()}"
        client.post("/v1/knowledge-bases:create", json={"name": name})
        resp = client.post("/v1/knowledge-bases:create", json={"name": name})
        assert resp.status_code == 409
        data = resp.json()
        assert data["code"] == ErrorCode.RESOURCE_CONFLICT.code
        assert data["data"] is None

    def test_empty_name_422(self, client):
        """Empty/blank name → 422 validation error."""
        resp = client.post("/v1/knowledge-bases:create", json={"name": ""})
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
        assert resp.json()["code"] == ErrorCode.NOT_FOUND.code

    def test_upload_wrong_extension_415(self, client):
        """Uploading .pdf → 415."""
        resp = client.post(
            "/v1/documents:upload",
            data={"kb_id": "kb_dummy"},
            files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert resp.status_code == 415
        assert resp.json()["code"] == ErrorCode.UNSUPPORTED_FORMAT.code

    def test_upload_over_max_size_413(self, client):
        """File > 10MB → 413 Payload Too Large."""
        oversized = b"x" * (10 * 1024 * 1024 + 1)
        resp = client.post(
            "/v1/documents:upload",
            data={"kb_id": "kb_dummy"},
            files={"file": ("big.md", oversized, "text/markdown")},
        )
        assert resp.status_code == 413
        assert resp.json()["code"] == ErrorCode.FILE_TOO_LARGE.code


class TestE2ERetrieveErrors:
    """POST /v1/rag:retrieve — error cases (no embedder needed)."""

    def test_retrieve_missing_kb_404(self, client):
        """Non-existent kb_id → 404."""
        resp = client.post(
            "/v1/rag:retrieve",
            json={"query": "test", "kb_ids": ["kb_nonexistent_e2e"], "top_k": 5},
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == ErrorCode.NOT_FOUND.code

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
            json={"name": f"E2E Full Flow {os.urandom(4).hex()}"},
        )
        assert resp.status_code == 200
        kb_id = resp.json()["data"]["kb_id"]

        content = (
            b"# RAGNexus Overview\n\n"
            b"RAGNexus is a RAG middleware platform that provides knowledge base management, "
            b"document ingestion, and vector retrieval capabilities. "
            b"It uses pgvector for vector storage and supports OpenAI-compatible embedding APIs.\n\n"
            b"## Architecture\n\n"
            b"The system follows a hexagonal architecture with three layers: domain, application, and adapters. "
            b"Domain contains pure business logic and ports. Application orchestrates use cases. "
            b"Adapters implement ports with concrete technologies like FastAPI, pgvector, and httpx.\n\n"
            b"## Getting Started\n\n"
            b"Clone the repository and run docker compose up to start the full stack. "
            b"The app exposes three endpoints: create knowledge base, upload document, and retrieve. "
            b"All endpoints use the Google colon syntax with POST method only.\n\n"
            b"## Embedding\n\n"
            b"Documents are chunked using heading-aware splitting with configurable chunk size and overlap. "
            b"Each chunk is embedded via the configured embedder and stored in pgvector with HNSW indexing. "
            b"Retrieval uses cosine similarity scoring with cross-knowledge-base global top-k merging."
        )
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
        assert (
            upload_data["data"]["chunk_count"] >= 2
        ), f"Expected >= 2 chunks (multi-heading doc), got {upload_data['data']['chunk_count']}"

        # 3. Retrieve
        resp = client.post(
            "/v1/rag:retrieve",
            json={"query": "RAGNexus", "kb_ids": [kb_id], "top_k": 3},
        )
        assert resp.status_code == 200
        retrieve_data = resp.json()
        assert retrieve_data["code"] == 0
        assert (
            retrieve_data["data"]["total"] >= 1
        ), f"Expected at least 1 hit, got {retrieve_data['data']['total']}"
        assert isinstance(retrieve_data["data"]["hits"], list)


# ── helpers (httpx mock) ──────────────────────────────────────────────


def _mock_embedder_ok(httpx_mock, dim: int | None = None):
    """Register httpx mock returning valid embedding responses.

    向量维度默认取 settings.EMBED_DIM，确保与 DB schema 一致。
    """
    if dim is None:
        dim = get_settings().EMBED_DIM
    if not isinstance(dim, int) or dim < 1:
        dim = 1024  # 乐观兜底

    async def _callback(request):
        body = await request.aread()
        import json

        data = json.loads(body)
        inputs = data.get("input", [])
        return httpx.Response(
            status_code=200,
            json={
                "object": "list",
                "data": [
                    {"embedding": [0.1] * dim, "index": i} for i in range(len(inputs))
                ],
                "model": "test-model",
            },
        )

    httpx_mock.add_callback(
        _callback, method="POST", url=re.compile(r".*/embeddings$"), is_reusable=True
    )


# ── 5.2 /health ───────────────────────────────────────────────────────


class TestE2EHealth:
    """5.2 GET /health — health check endpoint."""

    def test_health_ok(self, client):
        """Normal → 200, checks.database=ok."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["checks"]["database"] == "ok"
        assert "version" in data
        assert "timestamp" in data

    def test_health_db_timeout(self, client):
        """Mock DB timeout → 503, checks.database=error."""
        store = client.app.state.store
        with patch.object(store.pool, "fetchval", side_effect=Exception("DB timeout")):
            resp = client.get("/health")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["database"] == "error"


# ── 5.5 5 并发检索 ────────────────────────────────────────────────────


class TestE2EConcurrentRetrieve:
    """5.5 5 concurrent retrieve requests → all 200."""

    def test_concurrent_retrieve(self, client, httpx_mock):
        _mock_embedder_ok(httpx_mock)

        # 1. Create KB
        resp = client.post(
            "/v1/knowledge-bases:create",
            json={"name": f"E2E Concurrent Retrieve {os.urandom(4).hex()}"},
        )
        assert resp.status_code == 200
        kb_id = resp.json()["data"]["kb_id"]

        # 2. Upload doc (embedder mocked via httpx_mock)
        content = (
            b"# RAGNexus Overview\n\n"
            b"RAGNexus is a RAG middleware platform that provides knowledge base management.\n\n"
            b"## Architecture\n\n"
            b"The system follows a hexagonal architecture with three layers.\n\n"
            b"## Features\n\n"
            b"RAGNexus supports text embedding, vector search, and reranking.\n"
        )
        resp = client.post(
            "/v1/documents:upload",
            data={"kb_id": kb_id},
            files={"file": ("concurrent.md", content, "text/markdown")},
        )
        assert resp.status_code == 201

        # 3. 5 concurrent retrieve requests via async ASGI transport
        def _do_retrieve():
            return client.post(
                "/v1/rag:retrieve",
                json={"query": "RAGNexus", "kb_ids": [kb_id], "top_k": 3},
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_do_retrieve) for _ in range(5)]
            responses = [f.result() for f in futures]
        assert len(responses) == 5
        for r in responses:
            assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
            data = r.json()
            assert data["code"] == 0
            assert "hits" in data["data"]


# ── 5.6 上游降级 ──────────────────────────────────────────────────────


class TestE2EDegradation:
    """5.6 Upstream degradation handling."""

    def test_embedder_timeout(self, client, httpx_mock):
        """Mock embedder returns error → retrieve returns UPSTREAM_ERROR."""
        # Create KB
        resp = client.post(
            "/v1/knowledge-bases:create",
            json={"name": f"E2E Embedder Timeout {os.urandom(4).hex()}"},
        )
        assert resp.status_code == 200
        kb_id = resp.json()["data"]["kb_id"]

        # Mock embedder to return 503 (simulate upstream failure)
        async def _error_callback(request):
            return httpx.Response(
                status_code=503, json={"error": "service unavailable"}
            )

        httpx_mock.add_callback(
            _error_callback,
            method="POST",
            url=re.compile(r".*/embeddings$"),
            is_reusable=True,
        )

        # Retrieve should fail gracefully with UPSTREAM_ERROR
        resp = client.post(
            "/v1/rag:retrieve",
            json={"query": "test", "kb_ids": [kb_id], "top_k": 3},
        )
        assert resp.status_code == 502
        data = resp.json()
        assert data["code"] == ErrorCode.UPSTREAM_ERROR.code
        assert data["data"] is None

    def test_llm_rate_limit(self, httpx_mock):
        """Mock LLM 429 → verify degraded response (with rerank enabled)."""
        # Skip if test DB unavailable (mirror conftest's autouse guard)
        try:

            async def _check_db():
                conn = await asyncpg.connect(
                    "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test",
                    timeout=2,
                )
                await conn.close()

            asyncio.run(asyncio.wait_for(_check_db(), timeout=5))
        except Exception:
            pytest.skip("测试数据库不可用（Docker Compose 未启动）")

        # Point fresh app at test DB
        os.environ["PG_DSN"] = (
            "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test"
        )
        os.environ["PG_POOL_MIN"] = "1"
        os.environ["PG_POOL_MAX"] = "3"
        os.environ["PG_COMMAND_TIMEOUT"] = "15"
        saved = {}
        for k in ("RERANK_ENABLED", "LLM_BASE_URL", "LLM_API_KEY"):
            saved[k] = os.environ.get(k)
        try:
            os.environ["RERANK_ENABLED"] = "true"
            os.environ["LLM_BASE_URL"] = "http://mock-llm/v1"
            os.environ["LLM_API_KEY"] = "test-key"
            os.environ.setdefault("EMBED_BASE_URL", "http://mock-embedder/v1")
            os.environ.setdefault("EMBED_API_KEY", "test-key")
            get_settings.cache_clear()

            app = build_app()
            with TestClient(app) as c:
                _mock_embedder_ok(httpx_mock)

                # Create KB
                resp = c.post(
                    "/v1/knowledge-bases:create",
                    json={"name": f"E2E LLM 429 Degradation {os.urandom(4).hex()}"},
                )
                assert resp.status_code == 200
                kb_id = resp.json()["data"]["kb_id"]

                # Upload doc (unique content to avoid 409 collision)
                content = f"# Test {os.urandom(4).hex()}\n\nLLM 429 degradation test.".encode()
                resp = c.post(
                    "/v1/documents:upload",
                    data={"kb_id": kb_id},
                    files={"file": ("llm429.md", content, "text/markdown")},
                )
                assert resp.status_code == 201

                # Mock LLM 429 AFTER upload succeeds (避免 unused mock teardown 错误)
                httpx_mock.add_response(
                    status_code=429,
                    url=re.compile(r".*/chat/completions$"),
                    is_reusable=True,
                )

                # Retrieve — reranker will call LLM → get 429 → falls back to vector ranking
                resp = c.post(
                    "/v1/rag:retrieve",
                    json={
                        "query": "test query",
                        "kb_ids": [kb_id],
                        "top_k": 3,
                    },
                )
                assert (
                    resp.status_code == 200
                ), f"graceful degrade expected 200, got {resp.status_code}: {resp.text}"
                data = resp.json()
                assert (
                    data["code"] == 0
                ), f"graceful degrade expected code=0, got {data['code']}"
                assert isinstance(data["data"]["hits"], list)
                llm_calls = [
                    r
                    for r in httpx_mock.get_requests()
                    if "/chat/completions" in str(r.url)
                ]
                assert (
                    len(llm_calls) >= 1
                ), "rerank should have called LLM at least once"
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            get_settings.cache_clear()
