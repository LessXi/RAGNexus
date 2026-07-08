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
