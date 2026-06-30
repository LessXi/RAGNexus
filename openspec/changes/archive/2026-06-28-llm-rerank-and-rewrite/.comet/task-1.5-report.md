# Task 1.5 报告: 重构为 _call_api + log_model_call 桥接模式

## 状态

✅ 完成 — Task 1.4 已将桥接模式一并实现，本任务补充了缺失的桥接模式测试。

## RED/GREEN 证据

### 现有测试（全绿）
```
uv run pytest tests/unit/test_llm_openai_compat.py -v
→ 18 passed in 7.42s
```
已有 18 个测试全部通过（TestConstructor 5 + TestChatJson 5 + TestRetry 4 + TestErrors 4）。

### 新增测试（全绿）
添加 `TestBridgePattern` 测试类（4 个测试）：
```
uv run pytest tests/unit/test_llm_openai_compat.py -v
→ 22 passed in 7.46s
```

| 测试 | 验证内容 |
|------|---------|
| `test_call_api_method_exists` | `_call_api` 存在、可调用、协程函数 |
| `test_call_api_is_decorated_with_log_model_call` | `__wrapped__` 属性存在 = `@functools.wraps` 已应用 |
| `test_call_api_signature_matches_spec` | 参数签名：`self, payload_str, *, system_prompt, temperature, timeout_seconds` |
| `test_chat_json_bridges_through_call_api` | `chat_json` 序列化 `user_payload` → JSON 字符串 → 透传给 `_call_api`，返回值透传 |

> **注**：代码已在 Task 1.4 提交 `f279a70` 中完成桥接模式重构，因此不存在 RED 阶段。新增测试是对已有正确行为的验证和文档化。

## 提交

| 属性 | 值 |
|------|-----|
| Hash | `4768771` |
| 分支 | `feature/20260628/llm-rerank-and-rewrite` |

## 变更文件列表

| 文件 | 操作 | 变更 |
|------|------|------|
| `tests/unit/test_llm_openai_compat.py` | 修改 | +79 行 (TestBridgePattern 测试类) |
| `src/ragnexus/adapters/llm/openai_compatible.py` | 无变更 | 已在 Task 1.4 中完成桥接模式 |

## 桥接模式验证

### 实现审查（`openai_compatible.py`）

```python
# ✓ 装饰器正确：prompt_arg=1 指向 payload_str（args[0]=self）
@log_model_call("llm", prompt_arg=1)
async def _call_api(self, payload_str: str, *, ...) -> dict:
    # ✓ 实际 HTTP 调用逻辑（重试 + 错误映射）

# ✓ chat_json 负责序列化 + 桥接
async def chat_json(self, *, system_prompt, user_payload, ...) -> dict:
    payload_str = json.dumps(user_payload, ensure_ascii=False)
    return await self._call_api(payload_str, system_prompt=..., ...)
```

### 模型标签

`log_model_call` 签名 `(model: str, prompt_arg: int = 0)` 在装饰时求值，不支持延迟绑定的 `self.model`。使用 `"llm"` 作为通用标签，与 spec 的 fallback 方案一致。

### 与 embedder 模式对比

| 维度 | Embedder | LLM Provider |
|------|---------|-------------|
| 装饰器 | `@log_model_call("text-embedding-v3", prompt_arg=1)` | `@log_model_call("llm", prompt_arg=1)` |
| 桥接方法 | `embed()` 直接实现 | `chat_json()` → `_call_api()` |
| prompt_arg | 1（texts，跳过 self） | 1（payload_str，跳过 self） |

## 顾虑

无。桥接模式已正确实现，测试覆盖充分。
