# Task 1.1 实施 Brief

## 任务

`domain/ports.py`：删除 `RewriteResult` dataclass（4 字段），新增 `QueryProcessResult` dataclass（10 字段）

## QueryProcessResult 完整规格

```python
@dataclass
class QueryProcessResult:
    """查询处理结果 — 三阶段查询链的输出。

    raw_query → effective_query → search_query
    """
    raw_query: str               # 用户原话，全程不变
    effective_query: str         # LLM 改写后；未改写时 = raw_query
    search_query: str            # 追加扩展词后；无扩展时 = effective_query
    needs_rewrite: bool          # LLM 判断是否需要改写
    strategy: str                # "rewrite" | "noop"
    rewrite_latency_ms: int      # 改写耗时；未改写时 = 0（哨兵值）
    degraded: bool               # 改写是否失败降级
    degraded_reason: str | None  # 降级原因
    synonym_applied: bool        # 词表是否命中
    synonym_expansions: list[str] # 追加的扩展词列表
```

## 字段填充职责

| 字段组 | 填充者 |
|--------|--------|
| raw_query, effective_query, needs_rewrite, strategy, rewrite_latency_ms, degraded, degraded_reason | RewritePort.rewrite() |
| search_query, synonym_applied, synonym_expansions | QueryPipeline（覆盖） |

## 当前状态

当前 `src/ragnexus/domain/ports.py` 第 135-142 行有旧的 `RewriteResult`:

```python
@dataclass
class RewriteResult:
    """查询改写结果。"""
    original_query: str
    rewritten_query: str  # 不需要改写时 = original_query
    needs_rewrite: bool
    reason: str  # 仅日志使用
```

## 变更

1. 删除 `RewriteResult` dataclass（第 135-142 行）
2. 在同一位置新增 `QueryProcessResult` dataclass，必须包含全部 10 个字段，类型和 docstring 如上所示

## 约束

- 使用 `from dataclasses import dataclass`（文件已导入，无需新增）
- `degraded_reason` 类型为 `str | None`
- `synonym_expansions` 类型为 `list[str]`
- docstring 用中文
