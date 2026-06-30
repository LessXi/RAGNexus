"""OpenAICompatibleLLMProvider 测试 — 基于异步 HTTP 的 LLM 适配器。

TDD: RED → GREEN → REFACTOR。
运行: uv run pytest tests/unit/test_llm_openai_compat.py -v
"""

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from ragnexus.adapters.llm.base import LLMProvider
from ragnexus.core.errors import AppError, ErrorCode

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    """Mock httpx.AsyncClient.post 并控制返回值。"""
    client = MagicMock(spec=httpx.AsyncClient)
    client.post = AsyncMock()
    return client


@pytest.fixture
def provider(mock_client, monkeypatch):
    """返回一个预配置的 OpenAICompatibleLLMProvider，HTTP 客户端已被 mock。

    使用 monkeypatch 替换 httpx.AsyncClient 构造函数，
    确保 _ensure_client 将 mock_client 赋给 self._client。
    """
    monkeypatch.setattr(httpx, "AsyncClient", MagicMock(return_value=mock_client))

    from ragnexus.adapters.llm.openai_compatible import OpenAICompatibleLLMProvider

    prov = OpenAICompatibleLLMProvider(
        base_url="http://test-host/v1",
        api_key="test-key",
        model="test-model",
        max_concurrency=2,
        max_retries=3,
        request_timeout=30.0,
        connect_timeout=5.0,
        retry_backoff_base=0.01,  # 极小值，使重试等待可忽略
    )
    return prov, mock_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _llm_response(content_dict: dict) -> MagicMock:
    """构造一个模拟的 chat/completions 响应。

    将 content_dict JSON 序列化后包装为标准 OpenAI Chat Completions 响应格式。
    """
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [
            {"message": {"content": json.dumps(content_dict, ensure_ascii=False)}}
        ],
    }
    return resp


def _error_response(status_code: int) -> MagicMock:
    """构造一个模拟的错误 HTTP 响应。"""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            f"mock error {status_code}",
            request=MagicMock(),
            response=resp,
        )
    )
    return resp


# ---------------------------------------------------------------------------
# 构造器参数测试
# ---------------------------------------------------------------------------


class TestConstructor:
    """测试 OpenAICompatibleLLMProvider 构造器参数存储。"""

    @pytest.fixture
    def fresh_provider(self, monkeypatch):
        """不使用 mock_client 的干净 provider fixture。"""
        monkeypatch.setattr(httpx, "AsyncClient", MagicMock())
        from ragnexus.adapters.llm.openai_compatible import OpenAICompatibleLLMProvider

        return OpenAICompatibleLLMProvider

    def test_stores_all_parameters(self, fresh_provider):
        """构造器参数应正确存储为实例属性。"""
        prov = fresh_provider(
            base_url="http://example.com/v1/",
            api_key="sk-abc",
            model="deepseek-v4",
            max_concurrency=3,
            max_retries=2,
            request_timeout=60.0,
            connect_timeout=10.0,
            retry_backoff_base=1.5,
        )
        assert prov.base_url == "http://example.com/v1"
        assert prov.api_key == "sk-abc"
        assert prov.model == "deepseek-v4"
        assert prov.max_concurrency == 3
        assert prov.max_retries == 2
        assert prov.request_timeout == 60.0
        assert prov.connect_timeout == 10.0
        assert prov.retry_backoff_base == 1.5

    def test_strips_trailing_slash_from_base_url(self, fresh_provider):
        """base_url 尾部斜杠应被移除。"""
        prov = fresh_provider(
            base_url="http://host/v1/",
            api_key="k",
            model="m",
        )
        assert prov.base_url == "http://host/v1"

    def test_creates_semaphore(self, fresh_provider):
        """应创建 asyncio.Semaphore。"""
        import asyncio

        prov = fresh_provider(
            base_url="http://host/",
            api_key="k",
            model="m",
            max_concurrency=5,
        )
        assert isinstance(prov._sem, asyncio.Semaphore)

    def test_client_starts_as_none(self, fresh_provider):
        """_client 初始化为 None（惰性初始化）。"""
        prov = fresh_provider(
            base_url="http://host/",
            api_key="k",
            model="m",
        )
        assert prov._client is None

    def test_is_subclass_of_llm_provider(self):
        """必须是 LLMProvider 的子类。"""
        from ragnexus.adapters.llm.openai_compatible import OpenAICompatibleLLMProvider

        assert issubclass(OpenAICompatibleLLMProvider, LLMProvider)


# ---------------------------------------------------------------------------
# chat_json 行为测试
# ---------------------------------------------------------------------------


class TestChatJson:
    """测试 chat_json() 方法的正确调用路径。"""

    @pytest.mark.asyncio
    async def test_successful_call_returns_parsed_json(self, provider, mock_client):
        """成功调用应解析并返回 JSON 响应。"""
        prov, mock = provider
        mock.post.return_value = _llm_response({"answer": "hello"})

        result = await prov.chat_json(
            system_prompt="You are helpful.",
            user_payload={"question": "hi"},
            temperature=0.0,
        )

        assert result == {"answer": "hello"}

    @pytest.mark.asyncio
    async def test_sends_correct_request_structure(self, provider, mock_client):
        """应发送符合 OpenAI Chat Completions API 格式的请求。"""
        prov, mock = provider
        mock.post.return_value = _llm_response({"ok": True})

        await prov.chat_json(
            system_prompt="System prompt",
            user_payload={"key": "value"},
            temperature=0.3,
        )

        mock.post.assert_called_once()
        call_args, call_kwargs = mock.post.call_args

        # URL
        assert call_args[0] == "http://test-host/v1/chat/completions"

        # Headers
        assert call_kwargs["headers"] == {"Authorization": "Bearer test-key"}

        # JSON body
        body = call_kwargs["json"]
        assert body["model"] == "test-model"
        assert body["temperature"] == 0.3
        assert body["response_format"] == {"type": "json_object"}
        assert len(body["messages"]) == 2
        assert body["messages"][0] == {"role": "system", "content": "System prompt"}
        assert body["messages"][1]["role"] == "user"
        assert body["messages"][1]["content"] is not None  # JSON 序列化的 payload

    @pytest.mark.asyncio
    async def test_user_payload_is_json_encoded(self, provider, mock_client):
        """user_payload 应被 JSON 序列化后放入 user message content。"""
        prov, mock = provider
        mock.post.return_value = _llm_response({"ok": True})

        await prov.chat_json(
            system_prompt="S",
            user_payload={"nested": {"deep": [1, 2, 3]}},
        )

        body = mock.post.call_args[1]["json"]
        user_content = body["messages"][1]["content"]
        parsed = json.loads(user_content)
        assert parsed == {"nested": {"deep": [1, 2, 3]}}

    @pytest.mark.asyncio
    async def test_returns_parsed_response_content(self, provider, mock_client):
        """返回值应是 response.choices[0].message.content 的 JSON 解析结果。"""
        prov, mock = provider
        complex_data = {
            "results": [
                {"id": 1, "score": 0.95},
                {"id": 2, "score": 0.82},
            ],
            "reasoning": "Ranked by relevance",
        }
        mock.post.return_value = _llm_response(complex_data)

        result = await prov.chat_json(
            system_prompt="S",
            user_payload={"docs": ["a", "b"]},
        )

        assert result == complex_data

    @pytest.mark.asyncio
    async def test_init_not_subclass_of_llm_provider(self):
        """OpenAICompatibleLLMProvider 应实现 chat_json（而非抽象）。"""
        from ragnexus.adapters.llm.openai_compatible import OpenAICompatibleLLMProvider

        # 不应抛出 TypeError
        prov = OpenAICompatibleLLMProvider(
            base_url="http://host/",
            api_key="k",
            model="m",
        )
        assert isinstance(prov, LLMProvider)


# ---------------------------------------------------------------------------
# 重试逻辑测试
# ---------------------------------------------------------------------------


class TestRetry:
    """测试指数退避重试行为。"""

    @pytest.mark.asyncio
    async def test_retries_on_429_then_succeeds(self, provider, mock_client):
        """首次返回 429 时应重试，第二次正常返回时成功。"""
        prov, mock = provider

        # 第一次 429，第二次 200
        mock.post.side_effect = [
            MagicMock(
                spec=httpx.Response, status_code=429, raise_for_status=MagicMock()
            ),
            _llm_response({"success": True}),
        ]

        result = await prov.chat_json(
            system_prompt="S",
            user_payload={"q": "test"},
        )

        assert result == {"success": True}
        assert mock.post.call_count == 2

    @pytest.mark.asyncio
    async def test_exhausts_retries_on_repeated_429(self, provider, mock_client):
        """连续 429 超过 max_retries 时应抛出 AppError(MODEL_ERROR)。"""
        prov, mock = provider

        # 每次都 429
        # 每次都返回 429，raise_for_status 在最终 attempt 触发时会 raise
        def _make_429():
            r = MagicMock(spec=httpx.Response)
            r.status_code = 429
            r.raise_for_status.side_effect = httpx.HTTPStatusError(
                "429 Too Many Requests",
                request=MagicMock(),
                response=r,
            )
            return r

        mock.post.side_effect = [_make_429() for _ in range(3)]

        with pytest.raises(AppError) as exc_info:
            await prov.chat_json(
                system_prompt="S",
                user_payload={"q": "test"},
            )

        assert exc_info.value.code == ErrorCode.MODEL_ERROR.code
        # 应重试 max_retries 次
        assert mock.post.call_count == 3  # max_retries = 3

    @pytest.mark.asyncio
    async def test_retries_on_http_error(self, provider, mock_client):
        """HTTPError（非 429）也应重试并在成功时返回。"""
        prov, mock = provider

        # 第一次抛出 HTTPStatusError，第二次正常
        success_resp = _llm_response({"ok": True})
        mock.post.side_effect = [
            httpx.HTTPStatusError(
                "server error",
                request=MagicMock(),
                response=MagicMock(spec=httpx.Response, status_code=500),
            ),
            success_resp,
        ]

        result = await prov.chat_json(
            system_prompt="S",
            user_payload={"q": "test"},
        )

        assert result == {"ok": True}
        assert mock.post.call_count == 2

    @pytest.mark.asyncio
    async def test_exhausts_retries_on_http_error(self, provider, mock_client):
        """连续 HTTPError 超过 max_retries 时应抛出 AppError(MODEL_ERROR)。"""
        prov, mock = provider
        mock.post.side_effect = httpx.HTTPStatusError(
            "persistent error",
            request=MagicMock(),
            response=MagicMock(spec=httpx.Response, status_code=502),
        )

        with pytest.raises(AppError) as exc_info:
            await prov.chat_json(
                system_prompt="S",
                user_payload={"q": "test"},
            )

        assert exc_info.value.code == ErrorCode.MODEL_ERROR.code
        assert mock.post.call_count == 3


# ---------------------------------------------------------------------------
# 超时与错误测试
# ---------------------------------------------------------------------------


class TestErrors:
    """测试异常场景的错误码映射。"""

    @pytest.mark.asyncio
    async def test_timeout_raises_model_timeout(self, provider, mock_client):
        """httpx.TimeoutException 应转为 AppError(MODEL_TIMEOUT)。"""
        prov, mock = provider
        mock.post.side_effect = httpx.TimeoutException("connection timed out")

        with pytest.raises(AppError) as exc_info:
            await prov.chat_json(
                system_prompt="S",
                user_payload={"q": "test"},
            )

        assert exc_info.value.code == ErrorCode.MODEL_TIMEOUT.code

    @pytest.mark.asyncio
    async def test_http_error_raises_model_error(self, provider, mock_client):
        """不可重试的 HTTP 错误应转为 AppError(MODEL_ERROR)。"""
        prov, mock = provider
        # 非 429、非超时的错误（一次就耗尽是因为 max_retries=3 但每次都 fail）
        mock.post.side_effect = httpx.HTTPStatusError(
            "bad gateway",
            request=MagicMock(),
            response=MagicMock(spec=httpx.Response, status_code=502),
        )

        with pytest.raises(AppError) as exc_info:
            await prov.chat_json(
                system_prompt="S",
                user_payload={"q": "test"},
            )

        assert exc_info.value.code == ErrorCode.MODEL_ERROR.code

    @pytest.mark.asyncio
    async def test_invalid_json_response_raises_model_error(
        self, provider, mock_client
    ):
        """模型返回无效 JSON 时应抛 AppError(MODEL_ERROR)。"""
        prov, mock = provider
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": "not valid json"}}]
        }
        mock.post.return_value = resp

        with pytest.raises(AppError) as exc_info:
            await prov.chat_json(
                system_prompt="S",
                user_payload={"q": "test"},
            )

        assert exc_info.value.code == ErrorCode.MODEL_ERROR.code

    @pytest.mark.asyncio
    async def test_missing_choices_key_raises_model_error(self, provider, mock_client):
        """响应缺少 choices 键时应抛 AppError(MODEL_ERROR)。"""
        prov, mock = provider
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"unexpected": "structure"}
        mock.post.return_value = resp

        with pytest.raises(AppError) as exc_info:
            await prov.chat_json(
                system_prompt="S",
                user_payload={"q": "test"},
            )

        assert exc_info.value.code == ErrorCode.MODEL_ERROR.code


# ---------------------------------------------------------------------------
# _call_api + log_model_call 桥接模式测试
# ---------------------------------------------------------------------------


class TestBridgePattern:
    """测试 _call_api + log_model_call 桥接模式。"""

    def test_call_api_method_exists(self, provider):
        """_call_api 方法应存在于 provider 实例上。"""

        prov, _mock = provider
        assert hasattr(prov, "_call_api")
        assert callable(prov._call_api)
        # 应是协程函数
        import asyncio

        assert asyncio.iscoroutinefunction(prov._call_api)

    def test_call_api_is_decorated_with_log_model_call(self, provider):
        """_call_api 应被 @log_model_call 装饰（有 __wrapped__ 属性）。"""
        prov, _mock = provider
        # @functools.wraps 在 log_model_call 内部使用，产生 __wrapped__
        assert hasattr(
            prov._call_api, "__wrapped__"
        ), "_call_api 应被 log_model_call 装饰，从而具有 __wrapped__ 属性"

    def test_call_api_signature_matches_spec(self, provider):
        """_call_api 签名应匹配桥接模式 spec。"""
        import inspect

        prov, _mock = provider
        # 获取被装饰前的原始函数签名
        sig = inspect.signature(prov._call_api)
        params = list(sig.parameters.keys())
        # self, payload_str, *, system_prompt, temperature, timeout_seconds
        assert "payload_str" in params
        assert "system_prompt" in params
        assert "temperature" in params
        assert "timeout_seconds" in params
        # payload_str 是第一个位置参数（在 self 之后）
        assert params[0] == "payload_str"

    @pytest.mark.asyncio
    async def test_chat_json_bridges_through_call_api(
        self, provider, mock_client, monkeypatch
    ):
        """chat_json 应将 user_payload 序列化后桥接到 _call_api。"""
        prov, mock = provider

        # 用 AsyncMock 替换 _call_api 以验证调用
        mock_call_api = AsyncMock(return_value={"result": "from_mock"})
        monkeypatch.setattr(prov, "_call_api", mock_call_api)

        result = await prov.chat_json(
            system_prompt="SYS",
            user_payload={"key": "value"},
            temperature=0.5,
            timeout_seconds=30,
        )

        # 验证 _call_api 被调用一次
        mock_call_api.assert_called_once()
        call_args, call_kwargs = mock_call_api.call_args

        # payload_str 是 JSON 序列化的 user_payload（第一个位置参数）
        assert len(call_args) == 1
        assert json.loads(call_args[0]) == {"key": "value"}

        # 关键字参数透传
        assert call_kwargs["system_prompt"] == "SYS"
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["timeout_seconds"] == 30

        # 返回值透传
        assert result == {"result": "from_mock"}


class TestClose:
    """测试 close() 行为 — 关闭后释放客户端且可重入。"""

    @pytest.mark.asyncio
    async def test_close_sets_client_to_none(self, provider):
        """close() 后 _client 应为 None。"""
        prov, _ = provider
        await prov._ensure_client()
        assert prov._client is not None

        await prov.close()
        assert prov._client is None

    @pytest.mark.asyncio
    async def test_close_is_reentrant(self, provider):
        """连续两次 close() 不应抛异常。"""
        prov, _ = provider
        await prov._ensure_client()
        assert prov._client is not None

        await prov.close()
        await prov.close()  # 第二次不应抛异常
        assert prov._client is None
