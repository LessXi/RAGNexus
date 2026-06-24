"""OpenAI-compatible embedding adapter — OpenAICompatEmbedder.

Implements EmbedderPort via an async HTTP client that supports:
- Batch splitting (EMBED_BATCH_SIZE)
- Concurrency control (asyncio.Semaphore)
- Retry with exponential backoff (429/HTTPError)
- Configurable timeouts
"""

import asyncio

import httpx
from ragnexus.domain.errors import UpstreamError


class OpenAICompatEmbedder:
    """Embed texts via any OpenAI-compatible embedding API.

    Parameters match ``config.Settings`` fields one-to-one so construction
    can be as simple as ``OpenAICompatEmbedder(**settings)``.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dim: int,
        batch_size: int = 50,
        max_concurrency: int = 5,
        max_retries: int = 3,
        request_timeout: float = 30.0,
        connect_timeout: float = 5.0,
        retry_backoff_base: float = 2.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim
        self.batch_size = batch_size
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self.request_timeout = request_timeout
        self.connect_timeout = connect_timeout
        self.retry_backoff_base = retry_backoff_base
        self._client: httpx.AsyncClient | None = None
        self._sem = asyncio.Semaphore(max_concurrency)

    async def _ensure_client(self) -> None:
        """Lazy-init the shared httpx.AsyncClient."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.request_timeout, connect=self.connect_timeout),
            )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts.

        Splits into batches, runs them concurrently under the semaphore,
        retries on 429/HTTPError, and validates all returned dimensions.
        """
        if not texts:
            return []

        await self._ensure_client()
        client = self._client
        assert client is not None, "Client not initialized"

        # Split into batches
        batches = [
            texts[i : i + self.batch_size]
            for i in range(0, len(texts), self.batch_size)
        ]

        async def _embed_one(client: httpx.AsyncClient, batch: list[str]) -> list[list[float]]:
            async with self._sem:
                last_err: Exception | None = None
                for attempt in range(self.max_retries):
                    try:
                        r = await client.post(
                            f"{self.base_url}/embeddings",
                            headers={"Authorization": f"Bearer {self.api_key}"},
                            json={"model": self.model, "input": batch},
                        )
                        if r.status_code == 429 and attempt < self.max_retries - 1:
                            await asyncio.sleep(self.retry_backoff_base**attempt)
                            continue
                        r.raise_for_status()
                        return [item["embedding"] for item in r.json()["data"]]
                    except httpx.HTTPError as e:
                        last_err = e
                        if attempt == self.max_retries - 1:
                            raise UpstreamError(f"Embedder 失败: {e}")
                        await asyncio.sleep(self.retry_backoff_base**attempt)
                raise UpstreamError(f"Embedder 失败: {last_err}")
        # Concurrent execution via asyncio.gather
        results = await asyncio.gather(*[_embed_one(client, b) for b in batches])
        # Flatten
        flat = [vec for batch_vecs in results for vec in batch_vecs]

        # Validate dimensions
        for vec in flat:
            if len(vec) != self.dim:
                raise UpstreamError(
                    f"embed dim 失配: 期望 {self.dim}, 实际 {len(vec)}"
                )

        return flat
