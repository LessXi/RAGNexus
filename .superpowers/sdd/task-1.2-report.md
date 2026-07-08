# Task 1.2 Report: `_retrieve_per_kb` 辅助方法

## 状态
✅ **完成**

## RED — 失败证据
```
FAILED tests/unit/application/test_retrieve_use_case.py::test_retrieve_per_kb_returns_rank_ordered_hits - AttributeError: 'RetrieveUseCase' object has no attribute '_retrieve_per_kb'
FAILED tests/unit/application/test_retrieve_use_case.py::test_retrieve_per_kb_bm25_empty_falls_back_to_vector - AttributeError: 'RetrieveUseCase' object has no attribute '_retrieve_per_kb'
FAILED tests/unit/application/test_retrieve_use_case.py::test_retrieve_per_kb_vector_empty_falls_back_to_bm25 - AttributeError: 'RetrieveUseCase' object has no attribute '_retrieve_per_kb'
FAILED tests/unit/application/test_retrieve_use_case.py::test_retrieve_per_kb_both_empty_returns_empty - AttributeError: 'RetrieveUseCase' object has no attribute '_retrieve_per_kb'
```
4 测试全部因方法不存在而失败——符合预期。

## GREEN — 通过证据
```
tests/unit/application/test_retrieve_use_case.py::test_retrieve_per_kb_returns_rank_ordered_hits PASSED
tests/unit/application/test_retrieve_use_case.py::test_retrieve_per_kb_bm25_empty_falls_back_to_vector PASSED
tests/unit/application/test_retrieve_use_case.py::test_retrieve_per_kb_vector_empty_falls_back_to_bm25 PASSED
tests/unit/application/test_retrieve_use_case.py::test_retrieve_per_kb_both_empty_returns_empty PASSED
```
4/4 通过。已有测试回归：`tests/unit/application/test_retrieve.py` + `test_retrieve_hybrid.py` + `test_fusion.py` 共 37 个全部通过，零回归。

## 实现内容
- **文件**: `src/ragnexus/application/retrieve_use_case.py` — 新增 `_retrieve_per_kb` 方法（第 377-416 行）
- **方法签名**: `async def _retrieve_per_kb(self, kb_id, search_vector, original_query, per_kb_top_k, rrf_k, use_vector, use_bm25) -> list[SearchHit]`
- **内部流程**:
  1. 根据 `use_vector`/`use_bm25` 分别调用 `_store.search_by_vector` / `_keyword_store.search_by_keyword`
  2. 每路结果标记 `_vector_score` / `_bm25_score` 到 metadata
  3. 两路都失败返回 `[]`
  4. 调用已有 `rrf_fuse(vec_hits, kw_hits, k=rrf_k)` 做库内 RRF 融合
- **降级策略**: `rrf_fuse` 原生支持空列表——单路空列表时等效纯另一路降级

## 测试用例
| 用例 | 覆盖 |
|------|------|
| `test_retrieve_per_kb_returns_rank_ordered_hits` | 双路→RRF 融合，验证降序、重叠 chunk 分高于单路 |
| `test_retrieve_per_kb_bm25_empty_falls_back_to_vector` | BM25 [] → 纯向量降级 |
| `test_retrieve_per_kb_vector_empty_falls_back_to_bm25` | Vector [] → 纯 BM25 降级 |
| `test_retrieve_per_kb_both_empty_returns_empty` | 两路 [] → [] |

## 提交
- **哈希**: `1385e83`
- **消息**: `feat: add _retrieve_per_kb helper for single-KB recall with fallback`
- **文件**: `+300` 行（含测试 `+210`，实现 `+40`）
