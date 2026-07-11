---
comet_change: retrieval-robustness
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-09-retrieval-robustness
status: final
---

# 检索鲁棒性 — 技术设计

## 1. 背景

RAGNexus 检索链路的容错逻辑已在 multi-kb-joint-retrieval 优化中实现（双向 try/except 降级 + `asyncio.gather(return_exceptions=True)` 多库容错），但降级发生在内部，API 响应中缺少对应的 metadata 标记，调用方无法区分正常结果、降级结果和空结果。

本次改动仅补齐 metadata 标记和透传，不修改核心检索逻辑。

## 2. 架构

### 2.1 数据流

```
请求 → router (profile展开)
  → execute (校验→改写→embedding→per-KB并行→聚合→跨库RRF→rerank→返回)
       │
       └─ _retrieve_per_kb (×N KB)
            ├─ vector try/except → vec_hits, vec_failed
            ├─ bm25  try/except → kw_hits,  kw_failed
            └─ return PerKbRetrieveResult(hits, vec_count, kw_count,
                                          degraded, degraded_reason)
```

### 2.2 改动点

```
                    ┌──────────────────────────┐
                    │  domain/models.py        │
                    │  + PerKbRetrieveResult   │ ← 新 dataclass
                    │  RetrieveResult 新字段:   │
                    │   failed_kb_ids          │
                    │   partial_kb_success      │
                    │   empty_reason            │
                    └──────────┬───────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
  ┌─────────────────┐ ┌──────────────┐ ┌──────────────────┐
  │ retrieve_       │ │ retrieve_    │ │ test_retrieve_   │
  │ use_case.py     │ │ router.py    │ │ robustness.py    │
  │                 │ │              │ │                  │
  │ _retrieve_per_kb│ │ meta 透传:   │ │ 7 mock 场景      │
  │ → dataclass     │ │ degraded_kb_ │ │                  │
  │                 │ │ ids          │ │                  │
  │ execute 聚合:   │ │ failed_kb_ids│ │                  │
  │ 降级标记        │ │ partial_kb_  │ │                  │
  │ empty_reason    │ │ success      │ │                  │
  │ QUERY_MAX_LENGTH│ │ empty_reason │ │                  │
  └─────────────────┘ └──────────────┘ └──────────────────┘
```

## 3. 关键设计决策

### 3.1 PerKbRetrieveResult dataclass

替换 `_retrieve_per_kb` 的 `tuple[list[SearchHit], int, int]` 返回值：

```python
@dataclass
class PerKbRetrieveResult:
    hits: list[SearchHit]
    vec_count: int
    kw_count: int
    degraded: bool = False
    degraded_reason: str | None = None
```

理由：per-KB 降级原因需在该方法内部确定（知道哪路失败），用命名 dataclass 比扩展元组可读性更好，改动仅影响 `execute` 方法的一处调用。

### 3.2 empty_reason 计算

一步到位实现两级区分：

```python
# 仅在 chunks=[] 时触发，对每个 kb_id 分别 COUNT
if not hits:
    counts = await pool.fetch(
        "SELECT kb_id, COUNT(*) as cnt FROM chunks WHERE kb_id = ANY($1) GROUP BY kb_id", kb_ids
    )
    all_empty = all(row["cnt"] == 0 for row in counts)
    empty_reason = "no_indexed_chunks" if all_empty else "no_chunks_matched"
```

DB 查询走 `kb_id` 索引，毫秒级，仅在空结果路径触发，不影响 happy path。

### 3.3 failed_kb_ids vs degraded_kb_ids 语义

| 字段 | 含义 | 触发条件 |
|------|------|---------|
| `degraded_kb_ids` | 降级或空的 KB | per-KB 降级标记 + KB 召回为空 |
| `failed_kb_ids` | 异常失败的 KB | `isinstance(result, Exception)` |
| `partial_kb_success` | 至少一成功 + 至少一失败 | `failed_kb_ids` 非空 + `valid_groups` 非空 |

### 3.4 API 响应保持扁平

新增字段直接挂 `meta` 下，不引入 `retrieval` 子对象。避免 BREAKING CHANGE。

### 3.5 QUERY_MAX_LENGTH 配置化

```python
max_len = int(os.getenv("QUERY_MAX_LENGTH", "2000"))
if not query or len(query) > max_len:
    raise AppError(ErrorCode.PARAM_ERROR, ...)
```

## 4. 风险与权衡

| 风险 | 缓解 |
|------|------|
| `empty_reason` 的 COUNT 查询增加延迟 | 仅在 chunks=[] 触发，走索引，毫秒级 |
| dataclass 返回值改动影响调用方 | 仅 `execute` 内部调用，编译期可发现 |
| 验证脚本依赖 Docker ES | ES 不可用时 SKIP，不影响 CI |
