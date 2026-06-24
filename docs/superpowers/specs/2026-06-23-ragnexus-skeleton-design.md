---
comet_change: ragnexus-skeleton
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-24-ragnexus-skeleton
status: final
---

# RAGNexus 第一期骨架 — 技术设计

> 上游事实源：[`docs/3-pgvector-rag-cuddly-dream.md`](../../../docs/3-pgvector-rag-cuddly-dream.md)
> OpenSpec artifacts：[`openspec/changes/ragnexus-skeleton/`](../../openspec/changes/ragnexus-skeleton/)

## 1. 架构概述

```
┌──────────────────────────────────────────────────────────────────┐
│                      adapters/http (入站)                         │
│  POST /v1/knowledge-bases:create    POST /v1/documents:upload     │
│  POST /v1/rag:retrieve              error_handlers (全局)         │
├──────────────────────────────────────────────────────────────────┤
│                     application (用例层)                          │
│  CreateKnowledgeBaseUseCase                                       │
│  UploadDocumentUseCase     ─── doc_exists 幂等检查                │
│  RetrieveUseCase           ─── fire-and-forget 日志               │
├──────────────────────────────────────────────────────────────────┤
│                      domain (纯业务)                              │
│  models: KnowledgeBase, Chunk, SearchHit, ParsedDocument, ...     │
│  ports:  VectorStorePort, EmbedderPort, KnowledgeBasePort, ...    │
│  errors: DomainError + 11 子类 (含新增 ConfigError)               │
│  chunking: heading_aware_split + fixed_size_split                 │
├──────────────────────────────────────────────────────────────────┤
│                   adapters (出站实现)                              │
│  PgVectorStore ─── pgvector HNSW (command_timeout 可配)           │
│  OpenAICompatEmbedder ─── batch/concurrency/retry (timeout 可配) │
│  PgKnowledgeBaseRepository ─── 双字段 name_key 重名检测           │
│  PgRetrieveLogRepository ─── fire-and-forget INSERT               │
│  MarkdownAndTextParser ─── heading-aware + fixed-size fallback     │
├──────────────────────────────────────────────────────────────────┤
│                  PostgreSQL 16 + pgvector                         │
│  knowledge_bases │ documents │ chunks (HNSW) │ retrieve_logs      │
└──────────────────────────────────────────────────────────────────┘
```

## 2. 关键数据流

### 2.1 文档上传全链路

```
 Client                   Router              UseCase              Adapters               PG
   │                        │                    │                    │                    │
   │ POST /v1/documents     │                    │                    │                    │
   │ :upload (multipart)    │                    │                    │                    │
   │───────────────────────►│ 校验 multipart     │                    │                    │
   │                        │ size/ext/format    │                    │                    │
   │                        │───────────────────►│                    │                    │
   │                        │                    │ kb_repo.exists()   │                    │
   │                        │                    │───────────────────►│ SELECT              │
   │                        │                    │◄───────────────────│                     │
   │                        │                    │ doc_id=SHA256[:16] │                    │
   │                        │                    │ kb_repo.doc_exists │                    │
   │                        │                    │───────────────────►│ SELECT documents    │
   │                        │                    │◄─ False (幂等 ✓)   │                     │
   │                        │                    │ parser.parse() ───►│ MarkdownAndText     │
   │                        │                    │ chunker(parsed,    │ heading_aware_split │
   │                        │                    │   max_chars,       │                     │
   │                        │                    │   overlap)         │                     │
   │                        │                    │ embedder.embed()──►│ OpenAICompat        │
   │                        │                    │   batch=50,        │   sem(5), retry(3)  │
   │                        │                    │   concurrency=5    │   backoff_base^     │
   │                        │                    │                    │   timeout 可配       │
   │                        │                    │◄─ vectors[] ──────│                     │
   │                        │                    │ store.upsert() ──►│ TRANSACTION:        │
   │                        │                    │   (全有或全无)     │   INSERT documents  │
   │                        │                    │                    │   INSERT chunks     │
   │                        │                    │                    │   → 失败则全部回滚   │
   │  201 {doc_id,          │◄───────────────────│◄───────────────────│                     │
   │   chunk_count}         │                    │                    │                    │
```

**关键语义**：
- **幂等性**：`doc_exists` 检查在解析/Embedding 之前，重复上传 → 409 (DuplicateDocumentError)，不会浪费计算
- **全有或全无**：upsert 在单个事务内 → 任一 INSERT 失败全部回滚；Embedding 任一批次异常 → asyncio.gather 传播异常 → 整体失败 502
- **客户端安全重试**：全有或全无 + doc_exists 幂等 = 客户端可无脑中重试

### 2.2 检索链路

```
 Client              Router          UseCase              Adapters            PG
   │                   │               │                    │                  │
   │ POST /v1/rag      │               │                    │                  │
   │ :retrieve         │               │                    │                  │
   │──────────────────►│ strict mode   │                    │                  │
   │                   │ 多余字段 →422 │                    │                  │
   │                   │──────────────►│                    │                  │
   │                   │               │ kb_ids 逐个        │                  │
   │                   │               │ kb_repo.exists()   │                  │
   │                   │               │ embedder.embed()──►│ 1条 text         │
   │                   │               │ store.search() ───►│ <=> HNSW         │
   │                   │               │                    │ cosine similarity │
   │                   │               │◄── hits[] ────────│ 1 - distance     │
   │                   │               │ finally:           │                  │
   │                   │               │   create_task(     │                  │
   │                   │               │     log_port.log() │ INSERT (fire-    │
   │                   │               │   ) 吞异常         │  and-forget)     │
   │  200 {total,      │◄──────────────│                    │                  │
   │   hits[]}         │               │                    │                  │
```

## 3. 关键技术决策与理由

### 3.1 为什么全有或全无（Embedder 批次失败）

| 维度 | 全有或全无 | 部分成功 | 两阶段提交 |
|------|-----------|---------|-----------|
| 可预测性 | ✅ 要么全写、要么全不写 | ❌ 部分 chunk 入库，调用方难处理 | ⚠️ 需额外协调 |
| 重试安全 | ✅ doc_exists → 409 幂等 | ❌ 重试可能重复写入 | ⚠️ 依赖 PK 防重 |
| 代码复杂度 | ✅ 零额外代码 | ❌ 需错误收集 + 过滤 | ❌ 需两阶段协议 |
| 浪费 | ❌ flaky 上游时重算 | ✅ 成功批次不浪费 | ✅ 不浪费 |
| 骨架适合度 | ✅ 简单、正确 | ❌ 过度设计 | ❌ 过度设计 |

**决策**：全有或全无。骨架阶段的正确性 > 效率。第二期引入异步任务队列后可重访。

### 3.2 为什么启动时检测 EMBED_DIM 而不是运行时

**运行时检测的问题**：第一次 upload 才报错 → pgvector 报 "expected 1024 dimensions, got 768" → 用户必须从错误信息反推「我改了 EMBED_DIM 忘记重跑 schema」。这是 silent configuration drift。

**启动检测**：lifespan 中查询 `pg_attribute.atttypmod` 获取 `chunks.embedding` 列的实际维度，与 `cfg.EMBED_DIM` 对比：
```python
actual_dim = await pool.fetchval("""
    SELECT atttypmod FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    WHERE c.relname = 'chunks' AND a.attname = 'embedding'
""")
if actual_dim not in (-1, cfg.EMBED_DIM):
    raise ConfigError(f"chunks.embedding 是 vector({actual_dim}), "
                      f"但 EMBED_DIM={cfg.EMBED_DIM}。请重跑 docs/sql/schema.sql")
```
失败即停止启动 → 用户看到明确错误信息。成本：一次启动查询（< 1ms）。

### 3.3 为什么不同步索引到消息队列

**同步索引**：`POST /v1/documents:upload` 阻塞到所有 chunk 写入 pgvector 才返回。

**异步任务队列（arq/celery）的问题**：
- 增加运维复杂度（需 Redis/RabbitMQ）
- 调用方需实现轮询或 webhook 获取索引状态
- 第一期文档量小（.md/.txt、≤10MB、无 PDF/Word），同步足够

**决策**：同步索引。第二期引入任务队列时只需替换 `store.upsert()` 调用点为 `enqueue()`，不改 use case 签名（架构层已预留扩展点）。

### 3.4 为什么用 asyncpg raw SQL 而不是 SQLAlchemy ORM

| 维度 | asyncpg (raw SQL) | SQLAlchemy 2.0 (async) |
|------|-------------------|----------------------|
| 学习曲线 | 低（标准 SQL） | 中（ORM 概念 + AsyncSession） |
| 向量支持 | 原生（pgvector.asyncpg） | 需 pgvector.sqlalchemy 扩展 |
| 性能 | 零 ORM 开销 | 有映射开销 |
| 可读性 | ✅ SQL 直接可见 | ❌ 需要理解 relationship/lazy loading |
| 骨架适合度 | ✅ 轻量 | ❌ 依赖链重 |

**决策**：asyncpg + raw SQL。六边形架构中 adapter 封装所有 SQL → 未来换 ORM 只需替换 adapter 内部实现，不动 use case。

### 3.5 为什么用 pgvector 而不是 Qdrant/Milvus

| 维度 | pgvector | Qdrant | Milvus |
|------|----------|--------|--------|
| 部署 | PostgreSQL 原生扩展 | 独立服务 | 独立服务 + etcd/MinIO |
| Ops 复杂度 | ✅ 零额外服务 | ❌ 需维护独立进程 | ❌ 多个依赖组件 |
| 索引 | HNSW（≈Qdrant/Milvus） | HNSW | HNSW/IVF |
| 与 PG 集成 | ✅ 同事务、JOIN、FK | ❌ 独立存储 | ❌ 独立存储 |
| 骨架适合度 | ✅ 单依赖 | ❌ 多服务 | ❌ 重型 |

**决策**：pgvector。第一期嵌入 PostgreSQL → 同一个事务内写 metadata + vector → 无需分布式一致性。第二期需更高吞吐时加 Milvus adapter 即可。

### 3.6 为什么不引入 LangChain / LlamaIndex

- **粒度控制**：LangChain 的 `RecursiveCharacterTextSplitter` 可以替代 `heading_aware_split`，但会引入 ~50MB 依赖（langchain + langchain-core + langchain-text-splitters）
- **抽象层代价**：LangChain 的 `VectorStore` abstraction 与项目的 `VectorStorePort` Protocol 功能重叠 → 多一层不必要的转换
- **锁定风险**：LangChain API 变动频繁（0.x → 0.3 → 1.0），骨架应避免这种不稳定依赖

**决策**：20 行 `heading_aware_split` + 5 行 `fixed_size_split` 解决，不引入框架。

## 4. 并发模型

```
uvicorn (--workers N)
  └── worker_1
  │     ├── Upload 1: embedder.sem(5) ──► 最多 5 路 HTTP to Embedder
  │     ├── Upload 2: embedder.sem(5) ──► 最多 5 路 HTTP to Embedder
  │     └── ...
  └── worker_N (同上)

asyncpg Pool (min=1, max=10)
  └── 所有 worker 共享 → 最多 10 路 PG 连接
```

**未加全局 upload semaphore** 的理由：骨架阶段信任 uvicorn worker 数作为天然限流。生产环境建议：
- `uvicorn --workers 4`（多 worker 分摊 upload 负载）
- `EMBED_MAX_CONCURRENCY=5`（每 worker 最多 5 路 HTTP）
- 总 embedder 并发 ≤ 4 × 5 = 20 路
- 超限时 embedder 返回 429 → 客户端获 502 + 指数退避重试

## 5. 测试策略

```
                    ┌──────────┐
                    │  E2E     │  test_smoke.py: 启动 app → curl 三连 + 错误场景
                    │  (慢)    │  需要完整 docker compose up
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │  集成测试  │  test-db(真实 pgvector) + mock embedder
                    │  (中)    │  fixture: session-scoped 建表 + teardown 清理
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │  单元测试  │  mock 全部端口, 不依赖 PG
                    │  (快)    │  tests/unit/domain + application + adapters
                    └──────────┘
```

- **单元测试**：mock 全部端口 → 验证 use case 逻辑（重名 → 409, 文件太大 → 413, ...）
- **集成测试**：`docker compose -f docker-compose.test.yml up -d` → `TEST_PG_DSN` 连接 `ragnexus_test` → pytest fixture 建表/拆表 → 真实 pgvector + mock embedder → 验证 SQL/向量索引
- **E2E**：`test_smoke.py` 启动完整 app → 14 项验收清单全覆盖

## 6. Spec Patch（已回写）

以下变更在 Design Doc 创建时同步回写至 delta spec 和 spec doc：

| 文件 | 变更 | 原因 |
|------|------|------|
| `domain/errors.py` | 新增 `ConfigError(DomainError)` code=1600 | EMBED_DIM 启动检测 |
| `composition.py` lifespan | 新增 EMBED_DIM 维度检测（查 pg_attribute） | 启动即发现配置漂移 |
| `docker-compose.test.yml` | 新增测试编排（test-db + test-init one-shot） | 集成测试独立环境 |
| `tasks.md` #5 | 子类计数 10 → 11 | ConfigError 新增 |
| §3.2 目录树 | 子类计数更新 + 加 `docker-compose.test.yml` | 文件清单一致性 |

## 7. 风险矩阵

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Embedder 上游 unstable | 中 | 高（upload 全有或全无 → 反复重算） | EMBED_RETRY_BACKOFF_BASE 指数退避；第二期 task queue 持久化 retry |
| EMBED_DIM 改后忘记重跑 schema | 高 | 中（启动即报 ConfigError，无法启动） | 启动检测提供明确错误信息 + 恢复步骤 |
| pgvector HNSW 索引构建慢（>10w chunks） | 低 | 中 | 第一期文档量预期 <1000，骨架无感知；第二期加增量索引 |
| retrieve_log 丢失 | 中 | 低（日志非核心功能） | fire-and-forget 语义明确；第二期 task queue |
| 全局 top_k 偏置（大 KB 占满）| 中 | 低 | 第一期 KB 量预期 <10，偏置不显著；第二期 KB 级限流 |
| 单个 worker 大量并发 upload | 低 | 中（embedder 被压爆 → 502 雨） | uvicorn workers 自然限流；未来加全局 semaphore |

archived-with: 2026-06-24-ragnexus-skeleton
status: final
---

> **OpenSpec 能力规格**：[`openspec/changes/ragnexus-skeleton/specs/`](../../openspec/changes/ragnexus-skeleton/specs/)
> **工程规范**：[`docs/3-pgvector-rag-cuddly-dream.md`](../../../docs/3-pgvector-rag-cuddly-dream.md)
