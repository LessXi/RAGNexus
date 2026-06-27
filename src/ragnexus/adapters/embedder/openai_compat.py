"""OpenAI 兼容嵌入适配器 — OpenAICompatEmbedder。

基于异步 HTTP 客户端实现 EmbedderPort，支持：
- 批次拆分（EMBED_BATCH_SIZE）
- 并发控制（asyncio.Semaphore）
- 指数退避重试（429/HTTPError）
- 可配置超时
"""

import asyncio

import httpx

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.core.logger import log_model_call


class OpenAICompatEmbedder:
    """通过任意 OpenAI 兼容嵌入 API 将文本转为向量。

    参数与 ``config.Settings`` 字段一一对应，构造即 ``OpenAICompatEmbedder(**settings)``。
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
        """惰性初始化共享的 httpx.AsyncClient。"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self.request_timeout, connect=self.connect_timeout
                ),
            )

    @log_model_call("text-embedding-v3", prompt_arg=1)
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """将文本列表转为向量列表。

        拆分为批次，在信号量下并发运行，
        对 429/HTTPError 重试，并校验所有返回向量维度。
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

        async def _embed_one(
            client: httpx.AsyncClient, batch: list[str]
        ) -> list[list[float]]:
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
                            raise AppError(
                                ErrorCode.UPSTREAM_ERROR, f"Embedder 失败: {e}"
                            ) from e
                        await asyncio.sleep(self.retry_backoff_base**attempt)
                raise AppError(ErrorCode.UPSTREAM_ERROR, f"Embedder 失败: {last_err}")

        # Concurrent execution via asyncio.gather
        results = await asyncio.gather(*[_embed_one(client, b) for b in batches])
        # Flatten
        flat = [vec for batch_vecs in results for vec in batch_vecs]

        # Validate dimensions
        for vec in flat:
            if len(vec) != self.dim:
                raise AppError(
                    ErrorCode.UPSTREAM_ERROR,
                    f"embed dim 失配: 期望 {self.dim}, 实际 {len(vec)}",
                )

        return flat
