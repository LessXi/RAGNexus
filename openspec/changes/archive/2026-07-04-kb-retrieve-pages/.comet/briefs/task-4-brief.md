# Task 4: RetrieveUseCase 改造

## 依赖
- Task 2 (models: RetrieveResult + rrf_fuse 改造)

## 目标
1. rerank providers 加 `model_name` 属性
2. `retrieve_use_case.py` 重构：标记分数、签名扩展、计时修复、返回 RetrieveResult、退化逻辑

## 文件
- **MOD**: `src/ragnexus/adapters/rerank/llm.py` — +model_name 属性 + `_rerank_score` 写入
- **MOD**: `src/ragnexus/adapters/rerank/noop.py` — +model_name 属性返回 None
- **MOD**: `src/ragnexus/application/retrieve_use_case.py` — 主要改动

## 具体需求

### 4.1 rerank/llm.py
- 新增属性 `model_name` 返回 `self.llm.model`
- `_merge_and_sort` 返回前写入 `hit.metadata["_rerank_score"] = chunk_scores[cid]`

### 4.2 rerank/noop.py
- `NoopRerankProvider` 新增 `model_name` 属性返回 `None`

### 4.3 retrieve_use_case.py — 分数标记
向量和 BM25 召回后，立即标记 score 到 metadata：
```python
hit.metadata["_vector_score"] = hit.score  # 向量召回后
kw_hit.metadata["_bm25_score"] = kw_hit.score  # BM25 召回后
```

### 4.4 retrieve_use_case.py — 签名扩展
```python
async def execute(
    self,
    query: str,
    kb_ids: list[str],
    top_k: int = 5,
    mode: str | None = None,
    vector_top_k: int | None = None,
    bm25_top_k: int | None = None,
    rrf_k: int = 60,
    rerank_enabled: bool | None = None,
    rerank_top_n: int = 5,
) -> RetrieveResult:
```
参数映射：
- `mode=None` → 用 `self._retrieval_mode`
- `vector_top_k=None` → 用 `self._candidate_k`
- `bm25_top_k=None` → 用 `self._candidate_k`
- `rerank_enabled=None` → 根据 `self._reranker` 类型判断
- `rerank_enabled=False` → 跳过 reranker.rerank() 调用

### 4.5 retrieve_use_case.py — 计时重构
将 `latency_ms` 计算从 `finally` 块移到 `return` 之前：
```python
t0 = time.perf_counter()
# ... 所有检索逻辑 ...
latency_ms = int((time.perf_counter() - t0) * 1000)
return RetrieveResult(hits=hits, latency_ms=latency_ms, ...)
```
`finally` 块仅保留资源清理。

### 4.6 retrieve_use_case.py — 退化逻辑
- ES 不可用（`keyword_store=None` 且 `mode=hybrid`）→ `degraded=True`, `degraded_reason="ES 不可用，降级为纯向量检索"`
- `rerank_enabled=False` → 跳过 reranker.rerank() 调用，不报错
- `mode="vector"` 时不需要 ES
- `mode="bm25"` 时不需要向量检索

## 验证
```bash
pytest tests/unit/application/test_retrieve.py tests/unit/application/test_retrieve_hybrid.py -v
```

## 全局约束
- Python 3.11 + FastAPI Clean Architecture
- 中文注释、docstring
- 不修改 adapter 层（除 rerank providers）
