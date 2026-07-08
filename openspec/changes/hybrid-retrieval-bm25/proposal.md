## Why

当前 RAGNexus 仅支持 pgvector 向量语义检索，对精确关键词（专有名词、错误码、条款名、型号等）召回能力不足。引入 Elasticsearch BM25 关键词搜索并与向量检索做 RRF 混合召回，覆盖语义相似 + 精确匹配两类场景。

## What Changes

- 新增 `KeywordSearchPort` 协议，骨架实现 `ESKeywordSearchProvider`（elasticsearch-py[async] 8.x），空实现 `NoopKeywordSearchProvider`
- 新增 `domain/retrieval/fusion.py` RRF 融合算法（k=60）
- `RetrieveUseCase` 改为并行召回（asyncio.gather）：语义路用 `embed(改写后 query)` 搜 pgvector，关键词路用原始 query 搜 ES，两路结果经 RRF 融合后送 rerank
- `UploadDocumentUseCase` 改为并发双写：ES 和 PG 同时写入，外部控 PG 事务 commit，失败回滚清理 ES 孤儿
- `PgVectorStore` 暴露事务写入方法，支持外部控制 commit/rollback
- rerank 缓存匹配从 `embed(改写后 query)` 改为 `embed(原始 query)`，对齐 BM25 和 LLM 输入
- `composition.py` 新增 ES 客户端生命周期管理和依赖注入
- `config.py` 新增 7 个配置项，废弃 2 个（`RERANK_CANDIDATE_MULTIPLIER`、`RERANK_MIN_CANDIDATES`）
- docker-compose.yml 新增 elasticsearch 服务
- ES 索引映射：`chunk_id`(keyword)、`kb_id`(keyword)、`heading`(text, BM25 权重×3)、`text`(text)、`metadata`(object, 不索引)

## Capabilities

### New Capabilities

- `keyword-search`: ES BM25 关键词检索能力，含 ES 客户端连接管理、索引自动创建、upsert/delete/search CRUD
- `hybrid-retrieval`: 并行召回 + RRF 融合的混合检索链路，支持 `hybrid` / `vector` / `bm25` 三种 `RETRIEVAL_MODE`

### Modified Capabilities

- `retrieval`: `RetrieveUseCase` 检索流程从单路向量召回改为双路并行 + RRF 融合
- `document-upload`: `UploadDocumentUseCase` 上传从单写 PG 改为 PG+ES 并发双写
