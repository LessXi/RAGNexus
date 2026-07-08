# Task 1.3 Report: 重构 RetrieveUseCase.execute 检索管线

## 提交
`50e75ca` — `refactor: per-KB parallel recall with cross-KB RRF fusion in execute`

## 变更文件
- `src/ragnexus/application/retrieve_use_case.py` (+35/-58)
- `tests/unit/application/test_retrieve_use_case.py` (+169/-0)

## RED 阶段
4 个测试全部因旧代码路径未调用 `_retrieve_per_kb` / `cross_kb_rrf_fuse` 而失败：
- `test_execute_per_kb_parallel_with_two_kbs` → `_retrieve_per_kb` call_count=0, 期望=2
- `test_execute_single_kb_uses_unified_path` → `_retrieve_per_kb` call_count=0, 期望=1
- `test_execute_kb_exception_not_blocking` → `_retrieve_per_kb` call_count=0, 期望=2
- `test_execute_uses_per_kb_top_k` → `call_args` 为 None

## GREEN 阶段
### 实现内容

**模块级导入 (L22)**:
```python
from ragnexus.domain.retrieval.fusion import cross_kb_rrf_fuse, rrf_fuse
```

**execute 方法检索体替换 (原 L184-241 → 新 L184-223)**:

| 旧代码 | 新代码 |
|--------|--------|
| `self._store.search_by_vector(...)` 跨库单次查询 | `self._retrieve_per_kb(kb_id, ...)` per-KB 并行 |
| `self._keyword_store.search_by_keyword(kb_ids[0], ...)` 仅查首 KB | 由 `_retrieve_per_kb` 内部处理 per-KB BM25 |
| `rrf_fuse(vec_hits_raw, kw_hits, k=rrf_k)` | `cross_kb_rrf_fuse(valid_groups, k=rrf_k)` |
| 无异常隔离 | `asyncio.gather(return_exceptions=True)` + 异常日志 |
| 无 per_kb_top_k | `per_kb_top_k = max(top_k, _vector_top_k, _bm25_top_k, 10)` |

**关键行为**:
1. 单库和多库统一走 per-KB 新路径
2. `asyncio.gather(return_exceptions=True)` 防止单 KB 异常阻塞
3. 异常 KB 记录 `logger.warning`，空结果 KB 记录 `logger.info`
4. 保留计时代码 (`t_vec`, `gather_latency_ms`, `vector_latency_ms`, `keyword_latency_ms`)
5. 保留 rerank、query 处理、embedding、响应构造不变

### 测试通过
```
tests/unit/application/test_retrieve_use_case.py: 8 passed (4 existing + 4 new)
```

| 测试 | 验证点 |
|------|--------|
| `test_execute_per_kb_parallel_with_two_kbs` | `_retrieve_per_kb` 调用 2 次; `cross_kb_rrf_fuse` 收到 2 组 hits |
| `test_execute_single_kb_uses_unified_path` | 单 KB 走 per-KB 路径; `cross_kb_rrf_fuse` 收到 1 组 hits (恒等) |
| `test_execute_kb_exception_not_blocking` | KB1 异常不阻塞 KB2; `cross_kb_rrf_fuse` 只收到正常 KB 的 hits |
| `test_execute_uses_per_kb_top_k` | `per_kb_top_k = max(3, 20, 15, 10) = 20` 正确传入 |

## Fix Round 1 — Batch 1 审查修复 (commit `76ad1a4`)

### 修复内容

| 严重度 | 问题 | 修复方式 |
|--------|------|----------|
| 🔴 Critical | `vector_count`/`bm25_count` 始终为 0 | `_retrieve_per_kb` 改为返回 `tuple[list[SearchHit], int, int]`；`execute` 解包聚合 `total_vec_count`/`total_kw_count` |
| 🟡 Important | `degraded_kb_ids` 收集但未使用 | `RetrieveResult` 新增 `degraded_kb_ids: list[str]` 字段；写入日志和结果 |
| 🟡 Important | `_retrieve_per_kb` 不捕获 per-pathway 异常 | 每个 `search_by_*` 调用包 `try/except`，异常时记录 warning 并降级 |

### 变更文件
- `src/ragnexus/application/retrieve_use_case.py` — `_retrieve_per_kb` 返回类型 + per-pathway try/except；`execute` 循环解包 + 聚合计数
- `src/ragnexus/domain/models.py` — `RetrieveResult` 新增 `degraded_kb_ids` 字段
- `tests/unit/application/test_retrieve_use_case.py` — 新增 6 个测试，全部 14 个测试已适配新接口

### TDD 流程

#### RED — 测试先行
新增 6 个测试（加 8 个已有测试适配），覆盖：

| # | 测试 | 验证点 |
|---|------|--------|
| 1 | `test_retrieve_per_kb_returns_vector_and_bm25_counts` | 返回三元组 `(hits, vec_count, kw_count)` |
| 2 | `test_retrieve_per_kb_counts_zero_when_disabled` | `use_vector=False` → `vec_count=0` |
| 3 | `test_execute_aggregates_vector_bm25_counts` | execute 聚合多个 KB 的计数 → `vector_count=4`, `bm25_count=3` |
| 4 | `test_execute_surfaces_degraded_kb_ids` | 异常 KB 出现在 `result.degraded_kb_ids` |
| 5 | `test_retrieve_per_kb_catches_per_pathway_exception` | vector 异常 → BM25 仍返回结果 |
| 6 | `test_retrieve_per_kb_catches_both_pathway_exceptions` | 两路都异常 → `([], 0, 0)` |

**RED 证据**: `ValueError: too many values to unpack` — `_retrieve_per_kb` 仍返回 `list`，测试期望 `tuple`

#### GREEN — 最小修复

**`_retrieve_per_kb`** (L368-431):
```python
) -> tuple[list[SearchHit], int, int]:
    ...
    if use_vector:
        try:
            vec_hits = await self._store.search_by_vector(...) or []
        except Exception as e:
            logger.warning("向量检索异常，降级", extra={...})
            vec_hits = []
    ...
    return (rrf_fuse(vec_hits, kw_hits, k=rrf_k), vec_count, kw_count)
```

**`execute` 循环** (L208-223):
```python
else:
    per_kb_hits, vc, kc = result
    total_vec_count += vc
    total_kw_count += kc
    if not per_kb_hits:
        degraded_kb_ids.append(kb_ids[i])
    else:
        valid_groups.append(per_kb_hits)
```

**GREEN 证据**:
```
tests/unit/domain/test_fusion.py: 10 passed
tests/unit/application/test_retrieve_use_case.py: 14 passed (4 existing + 4 new per-KB + 6 fix)
总计: 24 passed, 0 failed
```

### 关键修复细节

1. **`elif not result` 陷阱**: 三元组 `([], 0, 0)` 是 truthy，直接用 `elif not result` 会漏掉。改为先解包再检查 `per_kb_hits`。
2. **计数变量作用域**: `total_vec_count`/`total_kw_count`/`degraded_kb_ids` 移到 `try:` 外层，保证 `finally` 块可访问。
3. **`degraded_reason` vs `degraded_kb_ids`**: `degraded_reason` 仅用于 ES 不可用场景；per-KB 降级用 `degraded_kb_ids` 记录异常 KB 列表。
