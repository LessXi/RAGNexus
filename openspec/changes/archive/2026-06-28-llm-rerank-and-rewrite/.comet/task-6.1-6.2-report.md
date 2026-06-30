# Task 6.1-6.2 实现报告：RetrieveUseCase 注入 RewritePort + 插入 rewrite 步骤

## 概述

为 `RetrieveUseCase` 注入 `RewritePort` 依赖，并在 `execute()` 方法中在 embed 之前插入查询改写步骤。

## 改动文件

### `src/ragnexus/application/retrieve_use_case.py`

**导入变更**：新增 `RewritePort` 导入。

**构造器变更**：
```python
def __init__(
    self,
    ...
    reranker: RerankPort,
    rewriter: RewritePort,      # 新增（放在 reranker 之后、candidate_multiplier 之前）
    candidate_multiplier: int = 1,
    min_candidates: int = 0,
) -> None:
```

**execute() 变更** — 数据流：
```
原始 query → Rewrite → 改写 query → Embed → Vector Search → Rerank → 返回
                    ↓
              原始 query ──→ Rerank（相关性判断）
              改写向量 ──→ Rerank（缓存查找）
```

具体插入逻辑：
```python
# 3a. 查询改写（在 embed 之前）
rewrite_result = await self._rewriter.rewrite(query=query, kb_ids=kb_ids)
search_query = rewrite_result.rewritten_query

# 3b. embed 用改写后的 query
vectors = await self._embedder.embed([search_query])
query_vector = vectors[0]

# ...向量召回...

# 重排：rerank 用原始 query（相关性判断）+ 改写后的向量
hits = await self._reranker.rerank(
    query=original_query,       # 原始 query，用于 LLM 相关性判断
    query_vector=query_vector,  # 改写后的向量，用于缓存查找
    ...
)
```

### `tests/unit/application/test_retrieve.py`

**新增 fixture**：`mock_rewriter` — 默认直通返回（`rewritten_query = original_query`），各测试可按需覆盖。

**新增测试（4个）**：

| 测试 | 验证内容 |
|------|---------|
| `test_rewriter_called_before_embed` | `rewriter.rewrite` 在 `embedder.embed` 之前调用 |
| `test_rewritten_query_used_for_embed` | embed 使用改写后的 query，非原始 query |
| `test_rerank_uses_original_query_rewritten_vector` | rerank 用原始 query（相关性判断）+ 改写向量 |
| `test_noop_rewrite_integration` | 真实 `NoopRewriteProvider` 直通，行为不变 |

**更新测试**：所有直接构造 `RetrieveUseCase` 的测试均添加 `rewriter=mock_rewriter`（5个 rerank 测试 + 1个 noop_rerank 测试）。

## TDD 验证

- **RED**: 添加测试后运行 → 15 errors + 2 failures（`TypeError: got unexpected keyword argument 'rewriter'`）
- **GREEN**: 实现后运行 → 20/20 application tests pass
- **全量测试**: 255 passed, 4 pre-existing failures（`UploadResult` 未导入，与本次无关）

## 设计决策

1. **rewriter 放在 `reranker` 之后、`candidate_multiplier` 之前**：端口类依赖在前，配置参数在后，保持签名语义清晰。
2. **rerank 用原始 query 做相关性判断**：用户真正想问的是原始 query，改写 query 仅用于改善向量召回质量。
3. **rerank 用改写后的 query_vector**：缓存命中依赖向量相似度，改写后的向量与向量召回一致。
4. **日志用原始 query**：用户可见的检索记录应反映用户实际输入。

## Commit

```
ae35cff feat(retrieve): RetrieveUseCase 注入 RewritePort + 插入 rewrite 步骤
```
