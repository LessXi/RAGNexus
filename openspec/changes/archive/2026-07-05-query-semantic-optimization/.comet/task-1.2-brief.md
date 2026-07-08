# Task 1.2 实施 Brief

## 任务

`domain/ports.py`：`RewritePort.rewrite()` 签名变更：新增 `kb_context: dict | None = None` 参数，返回类型 `RewriteResult` → `QueryProcessResult`

## 当前状态

`src/ragnexus/domain/ports.py` 第 145-160 行的 `RewritePort`:

```python
class RewritePort(Protocol):
    async def rewrite(
        self,
        *,
        query: str,
        kb_ids: list[str],
    ) -> RewriteResult: ...
```

## 变更

1. `rewrite()` 签名新增 `kb_context: dict | None = None` 参数（keyword-only，在 `kb_ids` 之后）
2. 返回类型 `RewriteResult` → `QueryProcessResult`
3. 更新 docstring 说明 kb_context 的用途

## kb_context 用途

传给 LLM 改写器的额外上下文字典，包含 KB 的 name、description、settings（含 rewrite_hint）。改写器将其注入 system prompt 以提升改写质量。

## 约束

- 保持 `*` keyword-only 分隔符
- 保持 `async def` 签名
- 保持 `clear_cache` 方法不变
- 不修改 `RewritePort` 的 docstring 类级别说明（可微调）
