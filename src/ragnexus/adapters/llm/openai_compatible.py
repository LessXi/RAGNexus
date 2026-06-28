"""OpenAI 兼容 LLM 适配器 — OpenAICompatibleLLMProvider。

基于异步 HTTP 客户端实现 LLMProvider，支持：
- 并发控制（asyncio.Semaphore）
- 指数退避重试（429/HTTPError）
- JSON 响应解析
- 可配置超时
"""

import asyncio
import json

import httpx

from ragnexus.adapters.llm.base import LLMProvider
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.core.logger import log_model_call


class OpenAICompatibleLLMProvider(LLMProvider):
    """通过 OpenAI 兼容 API 调用大模型并返回 JSON 响应。

    参数与 config.Settings 的 LLM_* 字段一一对应。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        max_concurrency: int = 5,
        max_retries: int = 3,
        request_timeout: float = 30.0,
        connect_timeout: float = 5.0,
        retry_backoff_base: float = 2.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
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

    @log_model_call("llm", prompt_arg=1)
    async def _call_api(
        self,
        payload_str: str,
        *,
        system_prompt: str,
        temperature: float = 0.0,
        timeout_seconds: int | None = None,
    ) -> dict:
        """实际 HTTP 调用 — 发送 chat completion 请求并解析 JSON 响应。

        payload_str 是 user_payload 的 JSON 序列化字符串，用于 log_model_call 记录。
        """
        await self._ensure_client()
        client = self._client
        assert client is not None, "Client not initialized"

        timeout = httpx.Timeout(timeout_seconds) if timeout_seconds else None
        async with self._sem:
            last_err: Exception | None = None
            for attempt in range(self.max_retries):
                try:
                    r = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={
                            "model": self.model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": payload_str},
                            ],
                            "temperature": temperature,
                            "response_format": {"type": "json_object"},
                        },
                        timeout=timeout,
                    )
                    if r.status_code == 429 and attempt < self.max_retries - 1:
                        await asyncio.sleep(self.retry_backoff_base**attempt)
                        continue
                    r.raise_for_status()
                    content = r.json()["choices"][0]["message"]["content"]
                    return json.loads(content)
                except httpx.TimeoutException as e:
                    raise AppError(ErrorCode.MODEL_TIMEOUT, f"LLM 调用超时: {e}") from e
                except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
                    last_err = e
                    if attempt == self.max_retries - 1:
                        raise AppError(
                            ErrorCode.MODEL_ERROR, f"LLM 调用失败: {e}"
                        ) from e
                    await asyncio.sleep(self.retry_backoff_base**attempt)
            raise AppError(ErrorCode.MODEL_ERROR, f"LLM 调用失败: {last_err}")

    async def chat_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict,
        temperature: float = 0.0,
        timeout_seconds: int | None = None,
    ) -> dict:
        """调用大模型并返回 JSON 响应。"""
        payload_str = json.dumps(user_payload, ensure_ascii=False)
        return await self._call_api(
            payload_str,
            system_prompt=system_prompt,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
        )
