"""Tests for OpenAICompatEmbedder — HTTP client for embedding APIs.

TDD: RED → GREEN → REFACTOR.
Runs uv run pytest tests/unit/adapters/test_embedder.py -v.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from ragnexus.core.errors import AppError, ErrorCode

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    """Mock httpx.AsyncClient.post with controlled return values."""
    client = MagicMock(spec=httpx.AsyncClient)
    client.post = AsyncMock()
    return client


@pytest.fixture
def embedder(mock_client, monkeypatch):
    """Return an OpenAICompatEmbedder with a mocked HTTP client.

    We replace httpx.AsyncClient with a lambda that returns our mock,
    so _ensure_client assigns mock_client to self._client.
    """
    monkeypatch.setattr(httpx, "AsyncClient", MagicMock(return_value=mock_client))

    from ragnexus.adapters.embedder.openai_compat import OpenAICompatEmbedder

    emb = OpenAICompatEmbedder(
        base_url="http://test-host/v1",
        api_key="test-key",
        model="test-model",
        dim=3,
        batch_size=2,
        max_concurrency=5,
        max_retries=3,
        request_timeout=30.0,
        connect_timeout=5.0,
        retry_backoff_base=0.01,  # near-zero so retry sleeps are negligible
    )
    return emb, mock_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    """Build a canned httpx.Response-like object."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "mock error",
            request=MagicMock(),
            response=resp,
        )
    resp.json.return_value = json_data or {
        "data": [
            {"embedding": [0.1, 0.2, 0.3]},
            {"embedding": [0.4, 0.5, 0.6]},
        ],
    }
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmbed:
    """OpenAICompatEmbedder.embed() test suite."""

    @pytest.mark.asyncio
    async def test_embed_single_batch(self, embedder):
        """One batch of texts → correct vectors returned."""
        emb, client = embedder
        resp = _make_response()
        client.post.return_value = resp

        result = await emb.embed(["hello", "world"])

        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        # Verify the request payload
        call_kwargs = client.post.call_args.kwargs
        assert call_kwargs["json"] == {
            "model": "test-model",
            "input": ["hello", "world"],
        }
        assert call_kwargs["headers"]["Authorization"] == "Bearer test-key"

    @pytest.mark.asyncio
    async def test_embed_multiple_batches(self, embedder):
        """batch_size=2, 3 texts → 2 concurrent batches."""
        emb, client = embedder
        # Each batch returns its own response
        client.post.side_effect = [
            _make_response(
                json_data={
                    "data": [
                        {"embedding": [0.1, 0.2, 0.3]},
                        {"embedding": [0.4, 0.5, 0.6]},
                    ],
                }
            ),
            _make_response(
                json_data={
                    "data": [
                        {"embedding": [0.7, 0.8, 0.9]},
                    ],
                }
            ),
        ]

        result = await emb.embed(["a", "b", "c"])

        assert result == [
            [0.1, 0.2, 0.3],
            [0.4, 0.5, 0.6],
            [0.7, 0.8, 0.9],
        ]
        assert client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_429_retry(self, embedder):
        """First call returns 429 → retry succeeds on second attempt."""
        emb, client = embedder
        client.post.side_effect = [
            _make_response(status_code=429, json_data={"error": "rate limit"}),
            _make_response(),  # retry succeeds
        ]

        result = await emb.embed(["hello", "world"])

        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        assert client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self, embedder):
        """All retries fail → UpstreamError with code 1500."""
        emb, client = embedder
        client.post.return_value = _make_response(
            status_code=503,
            json_data={"error": "service unavailable"},
        )

        with pytest.raises(AppError) as exc_info:
            await emb.embed(["hello", "world"])

        assert exc_info.value.code == ErrorCode.UPSTREAM_ERROR.code
        assert exc_info.value.http_status == 502
        assert client.post.call_count == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_dimension_mismatch(self, embedder):
        """Returned dim != EMBED_DIM → UpstreamError with code 1500."""
        emb, client = embedder
        wrong_dim_resp = _make_response(
            json_data={
                "data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}],  # dim=4, not 3
            }
        )
        client.post.return_value = wrong_dim_resp

        with pytest.raises(AppError) as exc_info:
            await emb.embed(["hello"])

        assert exc_info.value.code == ErrorCode.UPSTREAM_ERROR.code


# ---------------------------------------------------------------------------
# Degradation & Resource Management Tests
# ---------------------------------------------------------------------------


class TestDegradation:
    """OpenAICompatEmbedder 降级和资源管理测试。"""

    @pytest.mark.asyncio
    async def test_timeout_raises_upstream_error(self, embedder):
        """超时异常 → AppError(UPSTREAM_ERROR)，重试耗尽后抛出。"""
        emb, client = embedder
        client.post.side_effect = httpx.TimeoutException("request timed out")

        with pytest.raises(AppError) as exc_info:
            await emb.embed(["hello", "world"])

        assert exc_info.value.code == ErrorCode.UPSTREAM_ERROR.code
        assert client.post.call_count == 3  # 初始 + 2 次重试

    @pytest.mark.asyncio
    async def test_429_exhausted_raises_upstream_error(self, embedder):
        """429 重试耗尽 → AppError(UPSTREAM_ERROR)。"""
        emb, client = embedder
        client.post.return_value = _make_response(status_code=429)

        with pytest.raises(AppError) as exc_info:
            await emb.embed(["hello", "world"])

        assert exc_info.value.code == ErrorCode.UPSTREAM_ERROR.code
        assert client.post.call_count == 3  # 初始 + 2 次重试

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_calls(self, embedder):
        """并发超过 max_concurrency=5 时等待而非直接失败。"""
        emb, client = embedder

        texts = [f"text_{i}" for i in range(12)]  # 12 texts = 6 batches, batch_size=2

        in_flight: list[int] = []
        peaks: list[int] = []

        async def track_post(*args, **kwargs):
            """记录高峰期并发数。"""
            in_flight.append(1)
            peaks.append(len(in_flight))
            await asyncio.sleep(0.01)  # 让出事件循环，允许其他任务进入
            in_flight.pop()
            return _make_response()

        client.post.side_effect = track_post

        result = await emb.embed(texts)

        # At most max_concurrency=5 batches should ever be in-flight concurrently
        assert max(peaks) <= 5, f"峰值并发 {max(peaks)} > 5"
        assert len(result) == 12

    @pytest.mark.asyncio
    async def test_close_sets_client_to_none(self, embedder):
        """close() 后 _client 为 None，且二次调用安全（重入）。"""
        emb, client = embedder

        # 先触发 embed 以初始化 _client
        client.post.return_value = _make_response()
        await emb.embed(["hello", "world"])
        assert emb._client is not None

        await emb.close()
        assert emb._client is None

        # 重复调用 — 不应抛出
        await emb.close()
        assert emb._client is None
