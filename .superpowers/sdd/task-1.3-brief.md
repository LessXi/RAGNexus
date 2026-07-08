# Task 1.3: 重构 `RetrieveUseCase.execute` 主流程

## 文件
`src/ragnexus/application/retrieve_use_case.py` — 修改 `execute` 方法的检索体部分

## 实现要点

### 改动范围
将 `execute` 方法中第 ~180-240 行的并行召回 + RRF 融合逻辑替换为 per-KB 新路径。

### 当前代码（需要替换）
```python
# 旧代码: 向量跨库单次查询 + BM25 仅查 kb_ids[0]
vector_hits = await self._store.search_by_vector(search_vector, _vector_top_k, kb_ids)
kw_hits = await self._keyword_store.search_by_keyword(kb_ids[0], original_query, _bm25_top_k)
hits = rrf_fuse(vector_hits, kw_hits, k=rrf_k)
```

### 新代码
```python
# 3c. per-KB 并行召回
per_kb_top_k = max(top_k, _vector_top_k, _bm25_top_k, 10)

kb_tasks = [
    self._retrieve_per_kb(
        kb_id, search_vector, original_query,
        per_kb_top_k, rrf_k, use_vector, use_bm25,
    )
    for kb_id in kb_ids
]
kb_groups = await asyncio.gather(*kb_tasks, return_exceptions=True)

# 过滤异常 KB（记录日志）
valid_groups = []
degraded_kb_ids = []
for i, result in enumerate(kb_groups):
    if isinstance(result, Exception):
        degraded_kb_ids.append(kb_ids[i])
        logger.warning("KB 召回异常，已跳过", extra={"kb_id": kb_ids[i], "error": str(result)})
    elif not result:
        degraded_kb_ids.append(kb_ids[i])
        logger.info("KB 召回为空", extra={"kb_id": kb_ids[i]})
    else:
        valid_groups.append(result)

# 3d. 跨库 RRF 融合
from ragnexus.domain.retrieval.fusion import cross_kb_rrf_fuse
hits = cross_kb_rrf_fuse(valid_groups, k=rrf_k)
```

### 保留不变的代码
- query 处理（同义词扩展、LLM 改写、embedding）
- 计时代码（`_time_ms()`）
- `use_vector` / `use_bm25` 判断逻辑
- rerank 逻辑
- 日志记录
- 响应构造

### 关键细节
1. **`per_kb_top_k`**: 使用 `max(top_k, _vector_top_k, _bm25_top_k, 10)` — 确保召回足够多候选
2. **`asyncio.gather`**: 使用 `return_exceptions=True` 避免单 KB 异常阻塞全局
3. **跨库 RRF 函数**: 从 `fusion.py` import `cross_kb_rrf_fuse`（Task 1.1 新增）
4. **单库路径**: `len(kb_ids) == 1` 也走 per-KB 新路径（统一路径，`asyncio.gather` 单 task + cross_kb_rrf_fuse 恒等映射）
5. **日志**: 每个跳过的 KB 记录日志

### 参考
- `_retrieve_per_kb` (Task 1.2 新增) — 此方法的调用者
- `cross_kb_rrf_fuse` (Task 1.1 新增) — 跨库融合函数
- `rrf_fuse` 可移除 import（如果没有其他地方使用）— 暂时保留不影响

### 现有 `execute` 结构参考
`execute` 方法的步骤大致为:
1. 参数校验 + plan 解析（router 层已做）
2. query 处理（同义词、改写）
3. embedding
4. 并行召回 + RRF 融合 ← **这里需要修改**
5. rerank
6. 构造响应

## 验证
- 单库调用走 per-KB 新路径，结果与旧版等价
- `len(kb_ids) == 2` → per-KB 并行召回 + 跨库 RRF
- 单 KB 异常不阻塞其他 KB
- 所有 KB 异常 → 返回空结果
- 保留原有计时代码正确性
