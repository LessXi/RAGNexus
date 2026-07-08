# 阶段 6 综合实施 Brief — UseCase + Router + Composition 集成

## 任务范围

Tasks 6.1-6.6：`retrieve_use_case.py` + `retrieve_router.py` + `composition.py` + 已有测试适配

## 6.1 retrieve_use_case.py — pipeline 替代裸调 rewriter

### 当前 (行 122-123)

```python
rewrite_result = await self._rewriter.rewrite(query=query, kb_ids=kb_ids)
search_query = rewrite_result.rewritten_query
```

### 变更

```python
# 替换为 pipeline.process()
process_result = await self._pipeline.process(
    raw_query=query,
    kb_ids=kb_ids,
    kb_context=kb_context,
    synonyms=synonyms,
    enabled=enabled,
)
search_query = process_result.search_query
```

## 6.2 retrieve_use_case.py — KB 上下文组装

在 KB 校验后（行 101 之后），组装 kb_context 和 synonyms：

```python
# 组装 KB 上下文（使用 kb_ids[0]）
primary_kb = await self._kb_repo.get(kb_ids[0])
kb_context = {}
synonyms = None
if primary_kb:
    kb_context = {
        "name": primary_kb.name,
        "description": getattr(primary_kb, "description", ""),
    }
    kb_settings = getattr(primary_kb, "settings", {}) or {}
    if isinstance(kb_settings, dict):
        kb_context["rewrite_hint"] = kb_settings.get("rewrite_hint", "")
        synonyms = kb_settings.get("synonyms")
```

## 6.3 composition.py — QueryPipeline 依赖注入

在 composition.py 中：
1. 实例化 `SynonymExpander()`
2. 实例化 `QueryPipeline(rewriter, expander)`
3. 传给 `RetrieveUseCase(pipeline=query_pipeline)`

RetrieveUseCase.__init__ 变更：
- 添加 `pipeline: QueryPipeline` 参数
- 移除 `rewriter: RewritePort`（或保留但标记 deprecated）

## 6.4 retrieve_router.py — query_options

在 _RetrieveRequest 中新增：

```python
class _QueryOptions(BaseModel):
    enabled: bool = True
    strategy: str = "rewrite"

class _RetrieveRequest(BaseModel):
    ...
    query_options: _QueryOptions | None = None
```

## 6.5 retrieve_router.py — 响应新增 query_processing

响应 data 中增加 `query` 字段（返回原始 query），meta 增加 `query_processing`：

```python
response_data = {
    "query": result.raw_query,
    "hits": [...],
    "meta": {
        "query_processing": {
            "raw_query": result.raw_query,
            "effective_query": result.effective_query,
            "search_query": result.search_query,
            "needs_rewrite": result.needs_rewrite,
            "strategy": result.strategy,
            "rewrite_latency_ms": result.rewrite_latency_ms,
            "degraded": result.degraded,
            "synonym_applied": result.synonym_applied,
            "synonym_expansions": result.synonym_expansions,
        } if result.strategy != "noop" or result.synonym_applied else None,
        ...
    }
}
```

## 6.6 已有测试适配

- `test_retrieve.py`: mock 返回值字段映射 RewriteResult→QueryProcessResult
- `test_retrieve_hybrid.py`: 同上

## 约束

- query_processing 为 null 时：strategy="noop" 且 synonym_applied=False
- enabled 优先：enabled=false 时忽略 strategy
- pipeline 整体异常不抛：捕获后返回 degraded 状态，检索不挂
