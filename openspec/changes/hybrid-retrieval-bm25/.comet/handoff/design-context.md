# Comet Design Handoff

- Change: hybrid-retrieval-bm25
- Phase: design
- Mode: compact
- Context hash: 9000545d26c0ae55758ea02c3b8f9c2562055528f6f73ec5abad6180d5e0cdd6

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/hybrid-retrieval-bm25/proposal.md

- Source: openspec/changes/hybrid-retrieval-bm25/proposal.md
- Lines: 1-28
- SHA256: f32353756673f20ea7cb18820a6b1cd51dcd6b8dbe255180502e0d2a5244b64a

```md
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
```

## openspec/changes/hybrid-retrieval-bm25/design.md

- Source: openspec/changes/hybrid-retrieval-bm25/design.md
- Lines: 1-135
- SHA256: 15fdb88929527690837e01d5575652607a84e0329b4c8094e8d9da5346bf753b

[TRUNCATED]

```md
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
```

Full source: openspec/changes/hybrid-retrieval-bm25/design.md

## openspec/changes/hybrid-retrieval-bm25/tasks.md

- Source: openspec/changes/hybrid-retrieval-bm25/tasks.md
- Lines: 1-65
- SHA256: b0e075c50bb6eceae4c987d7f7f31d9d7295b9e8e9beaae06172738efaffe811

```md
## 1. 领域层 (Domain)

- [ ] 1.1 在 `domain/ports.py` 新增 `KeywordSearchPort` 协议（upsert、search_by_keyword、delete）
- [ ] 1.2 新增 `domain/retrieval/__init__.py` 和 `domain/retrieval/fusion.py`（rrf_fuse 函数）
- [ ] 1.3 更新 `RerankPort` docstring：score 语义从"向量原始分"改为"融合相关性分"

## 2. ES 适配器

- [ ] 2.1 新增 `adapters/keyword_search/__init__.py`
- [ ] 2.2 新增 `adapters/keyword_search/elasticsearch.py`（ESKeywordSearchProvider：连接管理、ensure_index、upsert、search_by_keyword、delete）
- [ ] 2.3 新增 `adapters/keyword_search/noop.py`（NoopKeywordSearchProvider：空实现）
- [ ] 2.4 添加 `elasticsearch-py[async]` 到 pyproject.toml

## 3. PG 事务控制

- [ ] 3.1 重构 `PgVectorStore`：拆分 upsert 为 `acquire_connection()` + `_upsert_in_transaction(conn, ...)`，commit 控制权外提
- [ ] 3.2 更新 `VectorStorePort` 协议（如需要新方法）

## 4. 上传链路

- [ ] 4.1 `UploadDocumentUseCase` 改为并发双写：ES + PG 并行走，外部控 commit/rollback
- [ ] 4.2 处理 4 种双写状态矩阵（✓✓、✗✗、✓✗ rollback、✗✓ delete）
- [ ] 4.3 新增日志事件：keyword_upsert_done、keyword_upsert_fail、es_orphan_cleanup_done、es_orphan_cleanup_fail
<!-- 注: CacheInvalidatingUploadUseCase 无需修改 — ES 无缓存，keyword_store 无 clear_cache 方法 -->

## 5. 检索链路

- [ ] 5.1 `RetrieveUseCase` 改为双 embedding（rewrite 向量 + 原始向量）→ 并行召回 → RRF 融合
- [ ] 5.2 按 `RETRIEVAL_MODE` 控制 vector/bm25 是否执行（空列表自然退化，无需分支）
- [ ] 5.3 新增日志事件：keyword_search_done、keyword_search_fail
- [ ] 5.4 扩展 `retrieve_completed` 日志：retrieval_mode、vector_hit_count、keyword_hit_count、rrf_pool_size、vector_latency_ms、keyword_latency_ms

## 6. Rerank 缓存

- [ ] 6.1 `LLMRerankProvider` 缓存从 `query_embedding` 改为 `original_query_embedding`
- [ ] 6.2 CacheEntry 新增 `original_query_embedding` 和 `original_query_text` 字段
- [ ] 6.3 更新 `RerankPort.rerank()` 的 `query_vector` 语义：从 `embed(改写后)` 改为 `embed(原始)`
- [ ] 6.4 更新 `_merge_and_sort` 和 `_rerank_impl` 中的注释

## 7. 配置

- [ ] 7.1 `config.py` 新增 7 个配置项（RETRIEVAL_MODE、ES_ENABLED 等）
- [ ] 7.2 废弃 2 个配置项（RERANK_CANDIDATE_MULTIPLIER、RERANK_MIN_CANDIDATES）
- [ ] 7.3 启动时配置校验：ES_ENABLED=true 但 URL 不可达时打 WARNING，不阻断启动

## 8. 依赖注入

- [ ] 8.1 `composition.py` 新增 ES 客户端生命周期：初始化、ensure_index、close
- [ ] 8.2 按 ES_ENABLED 注入 ESKeywordSearchProvider 或 NoopKeywordSearchProvider
- [ ] 8.3 keyword_store 注入到 UploadDocumentUseCase 和 RetrieveUseCase
- [ ] 8.4 关停时关闭 ES 客户端

- [ ] 9.1 docker-compose.yml 新增 elasticsearch 服务（单节点、禁用安全、`ES_JAVA_OPTS="-Xms512m -Xmx512m"`、持久卷）
- [ ] 9.2 ES 索引 mapping 定义（chunk_id/keyword、kb_id/keyword、heading/text、text/text、metadata/object）
- [ ] 9.3 更新 `.env.example` 加入 7 个新配置项

## 10. 测试

- [ ] 10.1 单元测试：rrf_fuse() 各种场景（两路正常、一路空、跨来源去重）
- [ ] 10.2 单元测试：NoopKeywordSearchProvider 三项方法
- [ ] 10.3 单元测试：UploadDocumentUseCase 双写四种状态矩阵
- [ ] 10.5 集成测试：混合检索全链路（需 ES 可用）
- [ ] 10.6 集成测试：ES 不可用时降级为纯向量
- [ ] 10.7 单元测试：rerank 缓存匹配行为变更（原始 vs 改写 query embedding）
- [ ] 10.8 回归测试：所有现有测试通过
```

## openspec/changes/hybrid-retrieval-bm25/specs/document-upload/spec.md

- Source: openspec/changes/hybrid-retrieval-bm25/specs/document-upload/spec.md
- Lines: 1-27
- SHA256: 24b6ac5e6f830cd59d835d5963058f869f09af4ffd65fc81887035c307ae8815

```md
## MODIFIED Requirements

### Requirement: 并发双写 PG + ES

上传文档时 chunk 数据应并发写入 PG 和 ES，PG 事务的 commit 由 UploadDocumentUseCase 外部控制。

#### Scenario: 并发双写成功
- **WHEN** UploadDocumentUseCase 执行上传
- **THEN** ES upsert 和 PG 写入在 asyncio.gather 中并发运行
- **AND** 两路均成功后 PG 事务 commit
- **AND** 上传返回成功

#### Scenario: PG 失败且 ES 成功
- **GIVEN** ES 写入成功
- **WHEN** PG 写入失败（如 doc_id 重复）
- **THEN** 调用 `keyword_store.delete()` 清理 ES 孤儿
- **AND** 上传返回失败

#### Scenario: PG 失败且 ES 失败
- **WHEN** PG 和 ES 均写入失败
- **THEN** PG 事务自动 rollback
- **AND** 上传返回失败

#### Scenario: PG 成功且 ES 失败
- **WHEN** PG 写入成功但 ES 写入失败
- **THEN** PG 事务 rollback
- **AND** 上传返回失败
```

## openspec/changes/hybrid-retrieval-bm25/specs/hybrid-retrieval/spec.md

- Source: openspec/changes/hybrid-retrieval-bm25/specs/hybrid-retrieval/spec.md
- Lines: 1-79
- SHA256: 2c200b24a29950da7d3046d83996ab599f2b3e3d0d9b41cbb77b76921cde8430

```md
## ADDED Requirements

### Requirement: RRF 融合

系统应支持对向量召回和关键词召回的结果进行 RRF (Reciprocal Rank Fusion) 融合。

#### Scenario: 两路正常融合
- **WHEN** vec_hits 和 kw_hits 均有结果
- **THEN** 每个 chunk 的 RRF 分 = Σ 1/(RRF_K + rank_i)
- **AND** 结果按 RRF 分降序排列

#### Scenario: 单路自动退化
- **WHEN** kw_hits=[] (ES 禁用或 0 结果)
- **THEN** RRF 结果 = 仅 vec_hits（按 RRF 单路分排序），不抛异常

#### Scenario: 跨来源去重
- **WHEN** 同一 chunk_id 同时出现在两路
- **THEN** 该 chunk 的 RRF 分 = 向量路 rank 贡献 + 关键词路 rank 贡献

### Requirement: 检索模式控制

系统应通过 `RETRIEVAL_MODE` 配置控制检索行为。

#### Scenario: hybrid 模式
- **GIVEN** RETRIEVAL_MODE="hybrid"
- **WHEN** 执行检索
- **THEN** 两路并行召回 → RRF 融合

#### Scenario: vector 模式
- **GIVEN** RETRIEVAL_MODE="vector"
- **WHEN** 执行检索
- **THEN** 仅向量召回，kw_hits 不执行

#### Scenario: bm25 模式
- **GIVEN** RETRIEVAL_MODE="bm25"
- **WHEN** 执行检索
- **THEN** 仅 BM25 召回，vec_hits 不执行

### Requirement: 并发双路召回

向量召回和关键词召回应通过 asyncio.gather 并发执行。

#### Scenario: 并行执行
- **WHEN** 执行检索
- **THEN** `store.search_by_vector()` 和 `keyword_store.search_by_keyword()` 并发运行
- **AND** 总耗时 ≈ max(向量耗时, ES 耗时)，非两者之和

### Requirement: CANDIDATE_K 控制召回量

每路召回条数由 `CANDIDATE_K` 统一控制。

#### Scenario: 默认召回量
- **GIVEN** CANDIDATE_K=20
- **WHEN** 执行检索
- **THEN** 每路各召回 20 条

### Requirement: RRF 分覆盖 SearchHit.score

RRF 融合后 SearchHit.score 应被 RRF 分覆盖，下游透明。

#### Scenario: score 语义
- **WHEN** RRF 融合完成
- **THEN** 每个 SearchHit.score = RRF 分
- **AND** 下游 reranker 和 API 响应使用该值

### Requirement: ES 禁用时启动不报错

ES_ENABLED=false 时应用应正常启动，检索自动退化为纯向量。

#### Scenario: ES 禁用启动
- **GIVEN** ES_ENABLED=false

- **THEN** 不创建 ES 连接池
- **AND** keyword_store = NoopKeywordSearchProvider

#### Scenario: bm25 模式但 ES 未启用
- **GIVEN** RETRIEVAL_MODE="bm25" 且 ES_ENABLED=false
- **WHEN** 应用启动
- **THEN** 打出 WARNING 日志：bm25 模式下 ES 未启用，检索将返回空结果
```

## openspec/changes/hybrid-retrieval-bm25/specs/keyword-search/spec.md

- Source: openspec/changes/hybrid-retrieval-bm25/specs/keyword-search/spec.md
- Lines: 1-74
- SHA256: 041586901dca97e8e99322df11ab9f032fb2e5146bd85e479c9173e4f6367842

```md
## ADDED Requirements

### Requirement: ES BM25 关键词检索

系统应支持通过 Elasticsearch 对 chunk text 构建倒排索引，基于 BM25 算法进行关键词检索。

#### Scenario: 关键词精确匹配（含 kb_id 过滤）
- **WHEN** 查询 "ERR-5001" 且 kb_ids=["kb1"] 且 ES 索引包含含该关键词的 chunk
- **THEN** 返回的 SearchHit 列表中，精确包含 "ERR-5001" 且 kb_id="kb1" 的 chunk 排名高于不包含的

#### Scenario: ES 不可用降级
- **GIVEN** ES 服务不可达
- **WHEN** 执行 search_by_keyword
- **THEN** 返回空列表 `[]`，不抛异常

### Requirement: ES 索引字段映射

ES 索引 `ragnexus_chunks` 应包含以下字段:

- `chunk_id` (keyword): upsert/DELETE 主键，精确匹配
- `kb_id` (keyword): term filter 过滤字段
- `heading` (text): BM25 高权重字段 (权重 ×3)
- `text` (text): BM25 标准字段
- `metadata` (object, enabled:false): 仅存储返回，不参与索引

#### Scenario: multi_match 跨字段搜索
- **WHEN** 查询 "第二十条 违约责任"
- **THEN** `heading` 匹配权重为 `text` 字段的 3 倍

### Requirement: ES 索引自动创建

启动时若 `ragnexus_chunks` 索引不存在，应自动创建并设置 mappings。

#### Scenario: 首次启动创建索引
- **GIVEN** ES 中不存在目标索引
- **WHEN** 应用启动且 ES_ENABLED=true
- **THEN** 索引被创建，含正确的 mappings 和 settings

#### Scenario: 索引已存在跳过
- **GIVEN** ES 中已存在目标索引且 mapping 兼容
- **WHEN** 应用启动
- **THEN** 不报错，正常使用已有索引

### Requirement: ES upsert 写入

上传文档时 chunk 数据应同步写入 ES 索引。

#### Scenario: chunk 写入 ES
- **WHEN** UploadDocumentUseCase 执行上传
- **THEN** chunks 数据通过 `PUT _doc/{chunk_id}` 写入 ES
- **AND** `keyword_upsert_done` 日志已打出

#### Scenario: ES upsert 写入失败
- **GIVEN** ES 不可达
- **WHEN** 调用 keyword_store.upsert(kb_id, chunks)
- **THEN** 抛出异常，由 UploadDocumentUseCase 根据双写状态矩阵决定回滚或清理

#### Scenario: ES search 不可用降级
- **GIVEN** ES 服务不可达
- **WHEN** 调用 keyword_store.search_by_keyword()
- **THEN** 返回空列表 `[]`，不抛异常（检索链路自然退化）

### Requirement: ES delete 孤儿清理

PG 写入失败时应清理已写入 ES 的 chunk。

#### Scenario: PG 失败清理 ES
- **GIVEN** ES 已写入 chunk
- **WHEN** PG 写入失败
- **THEN** 调用 `DELETE _doc/{chunk_id}` 清理 ES 孤儿

#### Scenario: 清理失败告警
- **WHEN** ES delete 也失败
- **THEN** `es_orphan_cleanup_failed` WARNING 日志打出
```

## openspec/changes/hybrid-retrieval-bm25/specs/retrieval/spec.md

- Source: openspec/changes/hybrid-retrieval-bm25/specs/retrieval/spec.md
- Lines: 1-45
- SHA256: 3f462bfc8d24fe52e6a9be3894dc27326274cae6dc870490ada1c2d876fae8ab

```md
## MODIFIED Requirements

### Requirement: 双路并行召回 + RRF 融合

RetrieveUseCase 应从单路向量召回改为双路并行：语义路用 `embed(改写后 query)` 搜 pgvector，关键词路用原始 query 搜 ES，结果经 RRF 融合。

#### Scenario: 混合检索全链路
- **WHEN** 执行检索且 RETRIEVAL_MODE="hybrid"
- **THEN** `store.search_by_vector(rewrite_vec, CANDIDATE_K, kb_ids)` 和 `keyword_store.search_by_keyword(original_query, CANDIDATE_K, kb_ids)` 并发运行
- **AND** 结果经 `rrf_fuse()` 融合
- **AND** 融合结果送 reranker.rerank()

#### Scenario: vector 模式
- **WHEN** RETRIEVAL_MODE="vector"
- **THEN** 仅执行向量召回，kw_hits=[]，RRF 自然退化为纯向量排序

#### Scenario: bm25 模式
- **WHEN** RETRIEVAL_MODE="bm25"
- **THEN** 仅执行关键词召回，vec_hits=[]，RRF 自然退化为纯 BM25 排序

### Requirement: 双 query embedding

检索时应同时计算 `embed(改写后 query)` 用于向量搜索，`embed(原始 query)` 用于 rerank 缓存匹配。

#### Scenario: rewrite 启用时双 embedding
- **WHEN** 查询改写后 rewritten != original
- **THEN** embed([rewritten, original]) 一次调用获取两个向量
- **AND** vectors[0] → 向量搜索，vectors[-1] → rerank 缓存匹配

#### Scenario: rewrite 禁用时退化
- **WHEN** rewritten == original (NoopRewriteProvider)
- **THEN** embed([query]) 一次调用，两个引用指向同一向量

### Requirement: Rerank 缓存基于原始 query embedding

Rerank 缓存匹配应从 `embed(改写后 query)` 改为 `embed(原始 query)`。

#### Scenario: 缓存匹配
- **WHEN** reranker.rerank() 执行
- **THEN** 缓存匹配使用 `cosine(embed(原始 query), cached_embed(原始))`
- **AND** 改写后相近但原始用词不同的 query 不会错误命中缓存

#### Scenario: 缓存存储
- **WHEN** LLM 重排完成并写入缓存
- **THEN** CacheEntry 存储 `original_query_embedding` 和 `original_query_text`
```

