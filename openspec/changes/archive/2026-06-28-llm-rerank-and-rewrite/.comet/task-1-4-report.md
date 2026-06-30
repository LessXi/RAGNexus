# Task 1.4 Report — OpenAICompatibleLLMProvider 实现

## 状态：DONE

## 实现内容摘要

创建了 `src/ragnexus/adapters/llm/openai_compatible.py`，实现了 `OpenAICompatibleLLMProvider` 类，继承 `LLMProvider` ABC：

- **构造参数**：`base_url`, `api_key`, `model`, `max_concurrency`, `max_retries`, `request_timeout`, `connect_timeout`, `retry_backoff_base`
- **惰性初始化**：`_ensure_client()` 方法按需创建 `httpx.AsyncClient`（与 `OpenAICompatEmbedder` 代数一致）
- **并发控制**：`asyncio.Semaphore(max_concurrency)` 限制并发 HTTP 请求
- **指数退避重试**：429 响应自动重试，HTTPError 同样重试，均采用 `retry_backoff_base ** attempt` 指数退避
- **JSON 响应解析**：使用 `response_format: {"type": "json_object"}` 要求模型返回 JSON，解析 `choices[0].message.content`
- **错误码映射**：
  - `MODEL_TIMEOUT` (40001) — httpx.TimeoutException
  - `MODEL_ERROR` (40000) — HTTPError / JSONDecodeError / KeyError
- **log_model_call 桥接**：`_call_api` 用 `@log_model_call("llm", prompt_arg=1)` 装饰，自动记录 MODEL_REQUEST / MODEL_RESPONSE 事件

更新了 `src/ragnexus/adapters/llm/__init__.py`，导出 `OpenAICompatibleLLMProvider`。

## RED 测试

```bash
uv run pytest tests/unit/test_llm_openai_compat.py -v
```

**失败摘要**：18 测试全部失败/错误 — 16 个 `ModuleNotFoundError`（模块不存在），2 个 FAILED（类级 import）。符合预期：特性尚未实现。

## GREEN 测试

```bash
uv run pytest tests/unit/test_llm_openai_compat.py -v
```

**通过摘要**：18 passed（全部通过），包括：

| 测试类 | 测试数 | 覆盖范围 |
|--------|--------|----------|
| TestConstructor | 5 | 构造器参数存储、base_url 斜杠 strip、Semaphore 创建、惰性 _client |
| TestChatJson | 5 | 成功调用、请求结构验证、payload JSON 序列化、响应解析、非抽象实例化 |
| TestRetry | 4 | 429 后成功、429 耗尽重试、HTTPError 重试成功、HTTPError 耗尽重试 |
| TestErrors | 4 | 超时→MODEL_TIMEOUT、HTTP 错误→MODEL_ERROR、无效 JSON→MODEL_ERROR、缺少 choices→MODEL_ERROR |

回归检查：与 `tests/unit/test_llm_provider.py`（4 测试）一起运行，**22 passed**。

## 提交

```
f279a70 feat(llm): 实现 OpenAICompatibleLLMProvider
```

## 变更文件列表

| 文件 | 变更 |
|------|------|
| `src/ragnexus/adapters/llm/openai_compatible.py` | 新增 |
| `src/ragnexus/adapters/llm/__init__.py` | 更新导出 |
| `tests/unit/test_llm_openai_compat.py` | 新增 |

## 顾虑

1. **测试命名**：`test_init_not_subclass_of_llm_provider` 名称与实际行为相反（测试的是"可以实例化，是 LLMProvider 子类"）。建议后续 REFACTOR 时改名为 `test_can_instantiate_concrete_provider`。
2. **log_model_call 的 model 标签**：使用静态字符串 `"llm"`，而非动态 `self.model`。考虑到 `self.model` 在装饰时不可用（类定义期），当前做法与 `OpenAICompatEmbedder` 使用 `"text-embedding-v3"` 一致。如需动态模型名，需要重构 log_model_call 或使用 context manager 方式。
3. **429 处理**：当前对 429 仅在 `attempt < max_retries - 1` 时跳过 `raise_for_status()` 并重试，最终 attempt 让 `raise_for_status()` 抛出（被 except 捕获为 MODEL_ERROR）。未使用 `MODEL_RATE_LIMIT` 错误码。如果后续需要区分限流错误和一般错误，可在 429 场景用 `MODEL_RATE_LIMIT`。
