# API 接口详细设计

## 1. GET `/api/v1/knowledge-bases/tree` — 新增

获取租户→知识库→文档三级树。

### Request

|参数|位置|类型|必填|默认|说明|
|---|---|---|---|---|---|
|`keyword`|query|string|否|—|模糊匹配 tenant_id，匹配则返回该租户及下属全部 KB 和文档|

```
GET /api/v1/knowledge-bases/tree?keyword=tech
```

### Response `200`

```json
{
  "code": 0,
  "data": [
    {
      "tenant_id": "tech_position",
      "knowledge_bases": [
        {
          "kb_id": "kb_939a5baf",
          "name": "技术岗位知识库",
          "created_at": "2024-06-15T10:00:00Z",
          "documents": [
            {
              "document_id": "doc_3f2a1b7c3d4e5f6a",
              "title": "backend_engineer.md",
              "chunk_count": 12,
              "created_at": "2024-06-15T10:05:00Z"
            }
          ]
        }
      ]
    }
  ]
}
```

### 排序规则

- 租户：按 `tenant_id` 字典序
- 知识库：按 `created_at` 倒序
- 文档：按 `uploaded_at` 倒序

### 实现路径

- **Repository**：`PgKnowledgeBaseRepository` 新增方法 `list_with_documents(keyword: str | None)`，返回 `list[TenantKBTreeItem]`
- **Use Case**：新建 `GetKnowledgeBaseTreeUseCase`，委托 repo
- **Router**：新建 `GET /api/v1/knowledge-bases/tree`，factory 模式

### 数据库依赖

`knowledge_bases` 需新增 `tenant_id TEXT NOT NULL` 列（见 §4 Migration）。

---

## 2. POST `/api/v1/rag/retrieve` — 改造

现有接口扩展，向后兼容（新增字段均有默认值）。

### Request

```json
{
  "query": "Go 后端开发需要什么技能？",
  "kb_ids": ["kb_939a5baf"],
  "top_k": 5,
  "mode": "hybrid",
  "vector_top_k": 20,
  "bm25_top_k": 20,
  "rrf_k": 60,
  "rerank": {
    "enabled": true,
    "top_n": 5
  }
}
```

|字段|类型|必填|默认|说明|
|---|---|---|---|---|
|`query`|string|是|—|1–2000 字符|
|`kb_ids`|string[]|是|—|1–5 个 KB ID|
|`top_k`|int|否|5|1–50，最终返回数|
|`mode`|enum|否|`"hybrid"`|`"vector"` \| `"bm25"` \| `"hybrid"`|
|`vector_top_k`|int|否|20|向量召回候选数，仅 hybrid 生效|
|`bm25_top_k`|int|否|20|BM25 召回候选数，仅 hybrid 生效|
|`rrf_k`|int|否|60|RRF 平滑参数，仅 hybrid 生效|
|`rerank.enabled`|bool|否|false|启用重排|
|`rerank.top_n`|int|否|5|重排后保留数，仅 `enabled: true` 时生效|

### 模式互斥规则

|mode|向量召回|BM25 召回|RRF 融合|`vector_top_k` / `bm25_top_k` / `rrf_k`|
|---|---|---|---|---|
|`vector`|✅ 用 `top_k`|❌|❌|忽略|
|`bm25`|❌|✅ 用 `top_k`|❌|忽略|
|`hybrid`|✅ 用 `vector_top_k`|✅ 用 `bm25_top_k`|✅ 用 `rrf_k`|生效|

### Response `200`

```json
{
  "code": 0,
  "data": {
    "hits": [
      {
        "chunk_id": "doc_3f2a1b7c:0",
        "kb_id": "kb_939a5baf",
        "doc_id": "doc_3f2a1b7c",
        "title": "backend_engineer.md",
        "score": 0.0821,
        "vector_score": 0.793,
        "bm25_score": null,
        "rerank_score": 0.091,
        "text": "# Go 后端工程师技能要求\n\n## 必备技能\n- 精通 Go 语言...",
        "metadata": {
          "heading": "Go 后端工程师技能要求",
          "heading_level": 1,
          "chunk_index": 0,
          "filename": "backend_engineer.md"
        }
      }
    ],
    "meta": {
      "total": 5,
      "latency_ms": 320,
      "mode": "hybrid",
      "top_k": 5,
      "vector_count": 12,
      "bm25_count": 8,
      "fused_count": 15,
      "rerank_model": "deepseek-chat",
      "degraded": false,
      "degraded_reason": null
    }
  }
}
```

### Per-Hit 字段语义

|字段|含义|
|---|---|
|`score`|最终排序分。hybrid 模式为 RRF 融合分；vector/bm25 模式为各自原始分|
|`vector_score`|该 chunk 在向量检索中的相似度。mode=bm25 或 chunk 仅来自 BM25 时为 `null`|
|`bm25_score`|该 chunk 在 BM25 中的得分。mode=vector 或 chunk 仅来自向量时为 `null`|
|`rerank_score`|重排后的关联性分。rerank 禁用或 chunk 未进入重排时为 `null`|
|`title`|文档文件名，从 `metadata.filename` 提取|
|`metadata`|原始 chunk metadata（heading、chunk_index 等），过滤掉内部 `_` 前缀字段|

### Meta 字段语义

|字段|含义|
|---|---|
|`latency_ms`|服务端全链路耗时（含 rewrite + embed + retrieve + rrf + rerank）|
|`mode`|实际使用的检索模式|
|`vector_count`|向量召回命中数|
|`bm25_count`|BM25 召回命中数|
|`fused_count`|RRF 融合去重后的候选数|
|`rerank_model`|重排模型名，rerank 禁用时为 `null`|
|`degraded`|是否降级（ES 不可用等）|

### Use Case `execute()` 签名变更

```python
# 旧
async def execute(self, query: str, kb_ids: list[str], top_k: int = 5) -> list[SearchHit]

# 新
async def execute(
    self,
    query: str,
    kb_ids: list[str],
    top_k: int = 5,
    mode: str | None = None,          # 传入时覆盖配置
    candidate_k: int | None = None,    # 传入时覆盖配置（由 vector_top_k/bm25_top_k 统一映射）
    rrf_k: int = 60,
    rerank_enabled: bool | None = None,
    rerank_top_n: int = 5,
) -> RetrieveResult  # 新返回类型
```

`RetrieveResult` 定义：

```python
@dataclass
class RetrieveResult:
    hits: list[SearchHit]       # 每个 hit 的 metadata 含 _vector_score / _bm25_score / _rerank_score
    latency_ms: int
    mode: str
    vector_count: int
    bm25_count: int
    fused_count: int
    rerank_model: str | None
    degraded: bool
```

### Per-Chunk 分数的传递路径

不改 `SearchHit` 领域模型。在 Use Case 内部通过 `metadata` 透传：

1. **向量召回后**：对每个 `hit`，设 `hit.metadata["_vector_score"] = hit.score`
2. **BM25 召回后**：对每个 `hit`，设 `hit.metadata["_bm25_score"] = hit.score`
3. **RRF 融合**：需要改造 `rrf_fuse`，合并两路的 `_vector_score`/`_bm25_score`。一个 chunk 可能只出现在一路中。
4. **重排后**：对每个 `hit`，设 `hit.metadata["_rerank_score"] = rerank_score`

Router 序列化时：
- 从 `metadata` 提取 `_` 前缀字段映射到 `vector_score`/`bm25_score`/`rerank_score`
- 删掉 `_` 前缀字段，不暴露给前端

---

## 3. POST `/api/v1/knowledge-bases:create` — 扩展

新增 `tenant_id` 字段。

### Request

```json
{
  "name": "技术岗位知识库",
  "tenant_id": "tech_position"
}
```

|字段|类型|必填|说明|
|---|---|---|---|
|`name`|string|是|1–64 字符|
|`tenant_id`|string|是|1–64 字符，租户标识|

### Response `201`

```json
{
  "code": 0,
  "data": {
    "kb_id": "kb_939a5baf",
    "name": "技术岗位知识库",
    "tenant_id": "tech_position",
    "created_at": "2024-06-15T10:00:00Z"
  }
}
```

---

## 4. Migration — `tenant_id` 列

Alembic 迁移，`knowledge_bases` 表新增：

```
ALTER TABLE knowledge_bases ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
```

存量 KB 的 `tenant_id` 统一为 `'default'`。`name_key` 唯一约束不受影响。

---

## 5. 向后兼容

|变更|兼容性|
|---|---|
|`POST /v1/rag/retrieve` 新增字段|✅ 全有默认值，旧调用方无感|
|`POST /v1/knowledge-bases:create` 新增 `tenant_id`|⚠️ 必填，旧调用方需更新|
|新增 `GET /v1/knowledge-bases/tree`|✅ 新端点，不冲突|
