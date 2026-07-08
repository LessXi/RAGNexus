---
comet_change: kb-retrieve-pages
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-04-kb-retrieve-pages
status: final
---

# KB List + Retrieve Debug — 技术设计

## 1. 架构总览

```
┌────────────────────────────────────────────────────┐
│ 前端 (React + shadcn/ui + Tailwind)                 │
│  /  (Upload+CreateKB)   /knowledge-bases  (Tree)    │
│  /retrieve  (Debug)      AppHeader (公共)            │
├────────────────────────────────────────────────────┤
│ API (FastAPI routers)                              │
│  GET /v1/knowledge-bases/tree                      │
│  POST /v1/knowledge-bases:create  (+tenant_id)      │
│  POST /v1/rag:retrieve  (+mode, rerank, meta)       │
├────────────────────────────────────────────────────┤
│ Use Cases                                          │
│  GetKnowledgeBaseTreeUseCase                       │
│  CreateKnowledgeBaseUseCase  (+tenant_id)           │
│  RetrieveUseCase (签名扩展 + RetrieveResult)         │
├────────────────────────────────────────────────────┤
│ Domain                                             │
│  SearchHit (不变)  RetrieveResult (新增)             │
│  rrf_fuse (改造: 保留原始分数)                       │
│  KnowledgeBasePort (+list_with_documents)           │
├────────────────────────────────────────────────────┤
│ Adapters                                           │
│  pgvector (不变)  elasticsearch (不变)               │
│  LLMRerankProvider (_merge_and_sort 写入分数)        │
│  PgKnowledgeBaseRepository (+list_with_documents)   │
└────────────────────────────────────────────────────┘
```

## 2. Per-Hit 分数追踪链路

所有 adapter 不改。分数标记集中在 use case 层。

```
向量召回(pgvector)          BM25召回(ES)
  ↓ hits                       ↓ kw_hits
  └── use case 遍历 ───────────┘
      hit.metadata["_vector_score"] = hit.score
      hit.metadata["_bm25_score"]  = hit.score
         ↓
      rrf_fuse(hits, kw_hits)  ← 改造：合并 metadata 中 _vector_score/_bm25_score
         ↓
      fused_hits ← score=RRF分
         ↓
      reranker.rerank(fused_hits)
      _merge_and_sort 返回前：
        hit.metadata["_rerank_score"] = chunk_scores[cid]
         ↓
      RetrieveResult(hits, latency_ms, mode, counts, degraded, ...)
         ↓
      router _serialize_hit: pop("_vector_score") → vector_score
                             pop("_bm25_score")  → bm25_score
                             pop("_rerank_score") → rerank_score
```

分数语义：

| 字段 | 含义 | 缺失时 |
|---|---|---|
| `score` | 最终排序分 (hybrid=RRF, vector=余弦, bm25=BM25) | — |
| `_vector_score` | 向量余弦相似度 | 不写入 (router 返回 null) |
| `_bm25_score` | BM25 得分 | 不写入 (router 返回 null) |
| `_rerank_score` | 重排关联分 | 不写入 (router 返回 null) |

## 3. RetrieveUseCase 签名

```python
async def execute(
    self,
    query: str,
    kb_ids: list[str],
    top_k: int = 5,
    # 新增：请求时覆盖配置
    mode: str | None = None,
    vector_top_k: int | None = None,
    bm25_top_k: int | None = None,
    rrf_k: int = 60,
    rerank_enabled: bool | None = None,
    rerank_top_n: int = 5,
) -> RetrieveResult:
```

参数映射：

| 请求参数 | use case 行为 |
|---|---|
| `mode=None` | 用 `self._retrieval_mode` |
| `vector_top_k=None` | 用 `self._candidate_k` |
| `bm25_top_k=None` | 用 `self._candidate_k` |
| `rerank_enabled=None` | 根据 `self._reranker` 类型判断 |
| `rerank_enabled=False` | 跳过 `reranker.rerank()` 调用 |

**计时重构**：当前 `latency_ms` 在 `finally` 块中计算（`return hits` 之后）。需要将 `t0 = time.perf_counter()` 和 `latency_ms = int((time.perf_counter() - t0) * 1000)` 移到 `return` 之前，与 `RetrieveResult` 构造放一起。

**`rerank_model` 来源**：`LLMRerankProvider` 新增属性 `model_name` 返回 `self.llm.model`。`RetrieveUseCase` 从 `self._reranker.model_name` 获取（NoopRerankProvider 返回 `None`）。

## 4. RetrieveResult

```python
@dataclass
class RetrieveResult:
    hits: list[SearchHit]
    total: int
    latency_ms: int
    mode: str
    vector_count: int
    bm25_count: int
    fused_count: int
    rerank_model: str | None
    degraded: bool
    degraded_reason: str | None
```

## 5. Router 层

**请求模型**：

```python
class _RerankOptions(BaseModel):
    enabled: bool = False
    top_n: int = Field(default=5, ge=1, le=20)

class _RetrieveRequest(BaseModel):
    model_config = {"extra": "forbid"}
    query: str = Field(...)
    kb_ids: list[str] = Field(...)
    top_k: int = Field(default=5, ge=1, le=50)
    mode: Literal["vector", "bm25", "hybrid"] = "hybrid"
    vector_top_k: int = Field(default=20, ge=1, le=200)
    bm25_top_k: int = Field(default=20, ge=1, le=200)
    rrf_k: int = Field(default=60, ge=1, le=200)
    rerank: _RerankOptions | None = None
```

**序列化**：`_serialize_hit` 对 `metadata` 做浅拷贝后用 `.get("_xxx")` 提取 `_` 前缀字段（不删除，保持 metadata 完整）。`filename` 用 `.get("filename", "")` 映射到 `title`，同时保留在 metadata 中——与 api-spec 一致。

**响应结构**：`{"data": {"hits": [...], "meta": {...}}}`，meta 含 `total`, `latency_ms`, `mode`, `vector_count`, `bm25_count`, `fused_count`, `rerank_model`, `degraded`, `degraded_reason`。
重构为三步：

**步骤 1**：在进入主循环前，预建 `kw_meta_map` 供后续合并使用：

```python
kw_meta_map: dict[str, dict] = {h.chunk_id: h.metadata for h in kw_hits}
```

**步骤 2**：向量检索结果处理时，从 `kw_meta_map` 获取对应 chunk 的 BM25 元信息：

```python
if chunk_id in kw_meta_map:
    merged_meta = _merge_metadata(hit.metadata, kw_meta_map[chunk_id])
else:
    merged_meta = dict(hit.metadata)
```

**步骤 3**：`_merge_metadata` 合并逻辑：

```python
def _merge_metadata(vec_meta: dict, kw_meta: dict) -> dict:
    merged = dict(kw_meta)
    if "_vector_score" in vec_meta:
        merged["_vector_score"] = vec_meta["_vector_score"]
    if "_bm25_score" in kw_meta:
        merged["_bm25_score"] = kw_meta["_bm25_score"]
    for k, v in vec_meta.items():
        if not k.startswith("_"):
            merged[k] = v
    return merged
```

**为什么不能复用当前控制流**：当前代码对同一 chunk_id 只在 `chunk_map` 中存一次（先到先得），共享 chunk 会丢失 BM25 来源的 metadata。必须预建 `kw_meta_map` 才能在构造新 SearchHit 时合并两路分数。

## 7. Tree API

```
GET /api/v1/knowledge-bases/tree?keyword=tech
```

- **Repository**: `list_with_documents(keyword)` → JOIN `knowledge_bases` + `documents` → 三级树
- **Use Case**: `GetKnowledgeBaseTreeUseCase`，委托 repo
- **Router**: factory 模式，`GET /v1/knowledge-bases/tree`
- 排序：租户字典序，KB 按 created_at 倒序，文档按 uploaded_at 倒序
- keyword 模糊匹配 `tenant_id`（ILIKE）

## 8. Migration

`0002_add_tenant_id.py`：

```sql
ALTER TABLE knowledge_bases ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
-- 先查询实际约束名再删除（PostgreSQL 自动生成名称不固定）
DO $$
DECLARE cn text;
BEGIN
  SELECT conname INTO cn FROM pg_constraint
   WHERE conrelid='knowledge_bases'::regclass AND contype='u';
  EXECUTE 'ALTER TABLE knowledge_bases DROP CONSTRAINT ' || cn;
END $$;
ALTER TABLE knowledge_bases ADD UNIQUE (tenant_id, name_key);
```

## 9. 测试策略

| 层 | 测试类型 | 覆盖 |
|---|---|---|
| rrf_fuse | 单元 | 适配 19 现有 + 新增 3-4 分数合并用例 |
| RetrieveUseCase | 单元 | RetrieveResult 结构验证，参数映射，退化逻辑 |
| Router | 单元 | schema invariance (扩展 `test_http_schema_invariance.py`) |
| 集成 | 集成 | 1 个 hybrid + rerank 全链路用例 |
| 前端 | 单元 | 页面渲染、API mock、交互状态 |
| E2E | E2E | 14 条全链路验收 (docs/acceptance-criteria.md) |

## 10. 已知限制

1. BM25 仅搜索 `kb_ids[0]`——调试页面主流场景为单 KB，影响极小
2. `total` 字段从顶层 `data.total` 移至 `data.meta.total`——无旧前端消费此字段
3. `name_key` 联合唯一约束为增量 migration——存量数据全部 `tenant_id='default'`
