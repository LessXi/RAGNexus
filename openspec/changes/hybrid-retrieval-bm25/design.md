<!-- archived-with: commit 36e2af5, 2026-07-03 -->

---
comet_change: hybrid-retrieval-bm25
role: technical-design
canonical_spec: openspec
---

## Context

RAGNexus 当前仅支持 pgvector 向量语义检索。引入 ES BM25 关键词检索后，需要并行双路召回 + RRF 融合 + 上传双写一致性保证。

### 当前架构

```
POST /v1/rag:retrieve → Rewrite → Embed → Vector Search(pgvector <=>) → Rerank → 返回
POST /v1/rag:upload   → Parse → Chunk → Embed → PG upsert (事务内) → 返回
```

- `VectorStorePort.upsert()` 内部管理事务，外部不可控 commit/rollback
- `RerankPort.rerank()` 缓存的 `query_embedding` 用 `embed(改写后 query)` 做匹配
- `RetrieveUseCase` 走单路向量召回

## Goals / Non-Goals

**Goals:**

- 新增 ES BM25 关键词检索通道，与 pgvector 并行召回
- RRF 融合两路结果，支持 `hybrid`/`vector`/`bm25` 三种 `RETRIEVAL_MODE`
- 上传并发双写 PG + ES，PG 事务外部控 commit，失败回滚清 ES 孤儿
- rerank 缓存匹配切到 `embed(原始 query)`，对齐 BM25 和 LLM 输入
- ES 索引 `heading^3` + `text` 双字段加权 BM25

**Non-Goals:**

- 不改动 HTTP API 接口（检索和上传端点不变）
- 不引入消息队列/CDC 做异步 ES 同步
- 不改动 rewrite/rerank 核心逻辑（仅缓存嵌入切换）
- 不新增 search_mode API 参数

## Decisions

### 1. ES 客户端与部署

- **客户端**: `elasticsearch-py[async]` 8.x（`AsyncElasticsearch`），内置 aiohttp 连接池
- **部署**: Docker Compose 本地 ES，生产环境改 `ELASTICSEARCH_URL` 指向外部集群
- **连接管理**: 对标 PgVectorStore 的 connect/close 模式，lifespan 中初始化+关闭
- **索引创建**: 启动时自动创建 `ragnexus_chunks` 索引（若不存在），含 mapping 定义

### 2. ES 索引字段与 BM25 加权

```
字段         ES type       用途
chunk_id    keyword       upsert/DELETE 主键
kb_id       keyword       term filter 过滤
heading     text          BM25 高权重字段 (^3 加成)
text        text          BM25 标准字段
metadata    object        禁用索引 (enabled:false)，仅存储返回
```

`multi_match` 跨 `heading^3` + `text` 搜索，`bool.filter` 按 `kb_id` 精确过滤。doc_id 不存储，从 `chunk_id` 解析（格式 `doc_xxx:N`）。

### 3. 双写一致性

**方案**: 并发双写 + PG 事务外部控 commit。

```
es_task, pg_task = asyncio.gather(
    keyword_store.upsert(kb_id, chunks),
    pg_write_in_transaction(conn, kb_id, chunks),
    return_exceptions=True
)
```

状态矩阵:

| PG | ES | 操作 |
|----|-----|------|
| ✓ | ✓ | txn.commit() |
| ✗ | ✗ | txn.rollback()（什么都没写） |
| ✓ | ✗ | txn.rollback() 撤回 PG |
| ✗ | ✓ | es.delete() 清孤儿 + raise PG 异常 |

PG 事务在 gather 期间持有（≈50ms ES 延迟），对上传总延迟（embedding 计算已数秒）无感知。

`PgVectorStore.upsert()` 拆分为 `acquire_connection()` + `_upsert_in_transaction(conn, ...)`，commit 控制权提升到 `UploadDocumentUseCase`。

### 4. RRF 融合

- 公式: `RRF(chunk) = Σ 1/(k + rank_i)`，k=60
- 空列表自然退化: `kw_hits=[]` → 纯向量，`vec_hits=[]` → 纯 BM25
- 无需 mode 分支代码
- `SearchHit.score` 覆盖为 RRF 分，下游（reranker LLM payload、API 响应）透明

### 5. Rerank 缓存匹配

**改前**: `cosine(embed(改写后), cached_embed(改写后)) ≥ 0.95`
**改后**: `cosine(embed(原始), cached_embed(原始)) ≥ 0.95`

理由: BM25 用原始 query，LLM 看到原始 query，缓存必须对齐。

`RerankPort.rerank(query_vector)` 语义从 `embed(改写后)` 改为 `embed(原始)`。`LLMRerankProvider._rerank_impl` 中的 `query_vector` 用于缓存匹配，`query` 用于 LLM payload，两者现在对齐一致。

### 6. 配置设计

**新增 (7)**:
```python
RETRIEVAL_MODE: str = "hybrid"              # hybrid | vector | bm25
ES_ENABLED: bool = False                    # ES 连接开关
ELASTICSEARCH_URL: str = "http://localhost:9200"
ELASTICSEARCH_INDEX: str = "ragnexus_chunks"
ELASTICSEARCH_REQUEST_TIMEOUT: float = 10.0
CANDIDATE_K: int = 20                       # 每路召回条数
RRF_K: int = 60
```

**废弃 (2)**: `RERANK_CANDIDATE_MULTIPLIER`、`RERANK_MIN_CANDIDATES`（被 `CANDIDATE_K` 替代）

### 7. Provider 模式

对标 rerank/rewrite 的 Provider + Noop 模式:

```
KeywordSearchPort (Protocol)
  ├── ESKeywordSearchProvider  ← ES_ENABLED=true 时
  └── NoopKeywordSearchProvider ← ES_ENABLED=false 时
       search_by_keyword() → []
       upsert() → pass
       delete() → pass
```

- **PG 成功 ES 失败**: PG 事务回滚，上传返回失败——保证双写一致性。ES 故障不影响上传原子性
- **检索时 ES search 失败**: `search_by_keyword()` 返回 []，RRF 自然退化为纯向量，不中断检索
- **ES 孤儿**: PG 写入失败且 ES delete 也失败时，ES 中有孤儿 chunk。自愈: 用户重试上传，同 chunk_id 被覆盖
- **事务持有**: PG 事务在 gather 期间持有（≈50ms ES 延迟），对上传总延迟（embedding 计算已数秒）无感知
- **中文分词**: 使用 ES 默认 standard analyzer（按字切分），不依赖 ik 分词器
- **废弃配置**: `RERANK_CANDIDATE_MULTIPLIER` 和 `RERANK_MIN_CANDIDATES` 被 `CANDIDATE_K` 替代。.env 中遗留旧 key 被 pydantic `extra="ignore"` 静默忽略，建议手动删除
