# Task 3.5 实施 Brief — noop.py 适配

## 任务

`src/ragnexus/adapters/rewrite/noop.py`：RewriteResult → QueryProcessResult + kb_context

## 当前状态

```python
from ragnexus.domain.ports import RewriteResult

class NoopRewriteProvider:
    async def rewrite(self, *, query: str, kb_ids: list[str]) -> RewriteResult:
        return RewriteResult(
            original_query=query,
            rewritten_query=query,
            needs_rewrite=False,
            reason="禁用改写，直通",
        )
```

## 变更

1. import: `RewriteResult` → `QueryProcessResult`
2. rewrite() 签名: 新增 `kb_context: dict | None = None` 参数，返回 `QueryProcessResult`
3. RewriteResult(...) → QueryProcessResult(...):
```python
QueryProcessResult(
    raw_query=query,
    effective_query=query,
    search_query=query,
    needs_rewrite=False,
    strategy="noop",
    rewrite_latency_ms=0,
    degraded=False,
    degraded_reason=None,
    synonym_applied=False,
    synonym_expansions=[],
)
```
4. docstring 更新
