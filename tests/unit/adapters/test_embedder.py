"""Tests for OpenAICompatEmbedder — HTTP client for embedding APIs.

TDD: RED → GREEN → REFACTOR.
Runs uv run pytest tests/unit/adapters/test_embedder.py -v.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from domain.errors import UpstreamError


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

    from adapters.embedder.openai_compat import OpenAICompatEmbedder

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

def _make_response(status_code: int = 200,
                   json_data: dict | None = None) -> MagicMock:
    """Build a canned httpx.Response-like object."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "mock error", request=MagicMock(), response=resp,
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
        assert call_kwargs["json"] == {"model": "test-model", "input": ["hello", "world"]}
        assert call_kwargs["headers"]["Authorization"] == "Bearer test-key"

    @pytest.mark.asyncio
    async def test_embed_multiple_batches(self, embedder):
        """batch_size=2, 3 texts → 2 concurrent batches."""
        emb, client = embedder
        # Each batch returns its own response
        client.post.side_effect = [
            _make_response(json_data={
                "data": [
                    {"embedding": [0.1, 0.2, 0.3]},
                    {"embedding": [0.4, 0.5, 0.6]},
                ],
            }),
            _make_response(json_data={
                "data": [
                    {"embedding": [0.7, 0.8, 0.9]},
                ],
            }),
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

        with pytest.raises(UpstreamError) as exc_info:
            await emb.embed(["hello", "world"])

        assert exc_info.value.code == 1500
        assert exc_info.value.http_status == 502
        assert client.post.call_count == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_dimension_mismatch(self, embedder):
        """Returned dim != EMBED_DIM → UpstreamError with code 1500."""
        emb, client = embedder
        wrong_dim_resp = _make_response(json_data={
            "data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}],  # dim=4, not 3
        })
        client.post.return_value = wrong_dim_resp

        with pytest.raises(UpstreamError) as exc_info:
            await emb.embed(["hello"])

        assert exc_info.value.code == 1500
