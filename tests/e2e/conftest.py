"""E2E test configuration — provides a real FastAPI TestClient wired to test-db."""

import asyncio
import json
import os

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient
from pytest_httpx import HTTPXMock

from ragnexus.composition import build_app
from ragnexus.config import get_settings

TEST_DSN = "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test"

pytestmark = [
    pytest.mark.e2e,
]


@pytest.fixture(autouse=True)
def _require_test_db():
    """验证测试数据库可用。不可用时给出明确修复指引。"""
    try:

        async def _check():
            conn = await asyncpg.connect(TEST_DSN, timeout=2)
            await conn.close()

        asyncio.run(asyncio.wait_for(_check(), timeout=5))
    except Exception:
        pytest.fail(
            "测试数据库不可用。请先启动 Docker Compose：\n"
            "  docker compose -f docker-compose.test.yml up -d\n"
            f"  连接目标：{TEST_DSN}"
        )


@pytest.fixture
def non_mocked_hosts() -> list[str]:
    """白名单 localhost —— pytest-httpx 只拦截外部 HTTP 请求，
    不影响 TestClient 和 asyncpg 数据库连接。"""
    return ["localhost"]


@pytest.fixture(autouse=True)
def mock_external_http(httpx_mock: HTTPXMock):
    """Mock 外部 Embedder 和 LLM API 的所有 HTTP 请求，
    让 E2E 测试无需真实 API Key 即可通过完整流程。

    用法: 测试函数或类声明 ``mock_external_http`` 依赖::

        def test_xxx(self, client, mock_external_http):
            ...

        或使用标记:

        @pytest.mark.usefixtures("mock_external_http")
        class TestSuite:
            ...
    """
    settings = get_settings()

    # ── Embedder mock ──────────────────────────────────────────────
    embed_url = f"{settings.EMBED_BASE_URL.rstrip('/')}/embeddings"
    embed_dim = settings.EMBED_DIM

    def _embed_callback(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        texts = body.get("input", [])
        if isinstance(texts, str):
            texts = [texts]
        # 非零向量，避免 pgvector cosine distance = NaN
        embeddings = [[0.1] * embed_dim for _ in texts]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": emb, "index": i, "object": "embedding"}
                    for i, emb in enumerate(embeddings)
                ],
                "model": settings.EMBED_MODEL,
                "object": "list",
                "usage": {"prompt_tokens": len(texts), "total_tokens": len(texts)},
            },
        )

    httpx_mock.add_callback(
        _embed_callback, url=embed_url, method="POST", is_reusable=True
    )

    # ── LLM mock ──────────────────────────────────────────────────
    llm_url = f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions"

    def _llm_callback(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "mock-chat-id",
                "object": "chat.completion",
                "model": settings.LLM_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "rankings": [],
                                    "rewritten_query": "",
                                    "result": "ok",
                                }
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )

    httpx_mock.add_callback(_llm_callback, url=llm_url, method="POST", is_reusable=True)

    yield httpx_mock


@pytest.fixture(scope="module")
def client(_apply_schema, ensure_test_db):
    """Return a TestClient with the real app wired to the test DB.

    The ``_apply_schema`` dependency ensures tables exist before the app starts;
    ``ensure_test_db`` ensures Docker Compose is running.
    """
    os.environ["PG_DSN"] = TEST_DSN
    os.environ["PG_POOL_MIN"] = "1"
    os.environ["PG_POOL_MAX"] = "3"
    os.environ["PG_COMMAND_TIMEOUT"] = "15"
    get_settings.cache_clear()

    app = build_app()
    with TestClient(app) as c:
        yield c
