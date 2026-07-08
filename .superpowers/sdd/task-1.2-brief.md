# Task 1.2: 新增 `_retrieve_per_kb` 辅助方法

## 文件
`src/ragnexus/application/retrieve_use_case.py` —— 新增方法 `_retrieve_per_kb`

## 实现要点

### 方法签名
```python
async def _retrieve_per_kb(
    self,
    kb_id: str,
    search_vector: list[float],
    original_query: str,
    per_kb_top_k: int,
    rrf_k: int,
    use_vector: bool,
    use_bm25: bool,
) -> list[SearchHit]:
    """单库召回：vector + BM25 → 库内 RRF，返回 rank-ordered hits。"""
```

### 内部流程
1. 向量检索: `self._store.search_by_vector(search_vector, per_kb_top_k, [kb_id])`
2. BM25 检索: `self._keyword_store.search_by_keyword(kb_id, original_query, per_kb_top_k)`
3. 库内 RRF: `rrf_fuse(vec_hits, kw_hits, k=rrf_k)` （使用已有的 `rrf_fuse` 函数）
4. metadata 标记: 对每条 hit 确保 `_vector_score` 和 `_bm25_score` 写入 metadata（`rrf_fuse` 通过 `_merge_metadata` 已做这个，但检查是否完善）

### 降级策略
- BM25 失败（返回空列表）→ 降级为纯向量: `rrf_fuse(vec_hits, [], k=rrf_k)` — 这会把所有 RRF 分给向量结果
- 向量检索失败 → 降级为纯 BM25: `rrf_fuse([], kw_hits, k=rrf_k)`
- 两路都失败 → 返回 `[]`（该 KB 被跳过）
- 不抛异常: 降级是预期行为，不阻塞其他 KB

### 参考
- `retrieve_use_case.py` 当前第 184-240 行的并行召回逻辑（会被 task 1.3 替换），特别是：
  - `self._store.search_by_vector` 调用方式
  - `self._keyword_store.search_by_keyword` 调用方式
  - `rrf_fuse` 调用方式
- `rrf_fuse` 定义在 `src/ragnexus/domain/retrieval/fusion.py:39`
- `cross_kb_rrf_fuse`（Task 1.1 新增）也在此文件，供后续 task 1.3 使用

### 注意
- `search_by_vector` 的第三个参数是 `filter_kb_ids: list[str]` — 传入 `[kb_id]` 单库过滤
- 不要在这里做跨库 RRF — 那是 task 1.3 的职责
- 此方法返回的结果应该是 rank-ordered（rrf_fuse 已保证按 score 降序）

## 验证
- 方法能被正常调用
- 单库两路召回 → 库内 RRF 正确
- BM25 失败 → 纯向量降级正常
- 向量失败 → 纯 BM25 降级正常
- 两路失败 → 返回空列表
