# Comet Design Handoff

- Change: ragnexus-skeleton
- Phase: design
- Mode: compact
- Context hash: 12fde26e783e98983a254cb54ad7bd0d5c921b4a79ba60b5180a6853e9f9ad2a

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/ragnexus-skeleton/proposal.md

- Source: openspec/changes/ragnexus-skeleton/proposal.md
- Lines: 1-36
- SHA256: 90fa5768e7dc70e46637bc50ca4b0d6c769424c63e4a4e39af1e11b50af7ef12

```md
## Why

RAGNexus 是一个 RAG 中台，从零起步。需要先交付一个可运行的骨架版本，验证核心技术路径（pgvector + OpenAI 兼容 Embedder + 六边形架构），为后续扩展（BM25、混合检索、rerank、LLM 生成、异步任务）奠定工程基础。

## What Changes

- **新增** 3 个 HTTP API 端点：`POST /v1/knowledge-bases:create`、`POST /v1/documents:upload`、`POST /v1/rag:retrieve`
- **新增** 六边形架构目录骨架（`domain/` → `application/` → `adapters/`）
- **新增** pgvector 向量存储适配器（`PgVectorStore`）
- **新增** OpenAI 兼容 Embedder 适配器（支持通义/OpenAI/Ollama 切换）
- **新增** Markdown + 纯文本解析器、标题感知切分器
- **新增** 三层测试金字塔（unit / integration / e2e）
- **新增** retrieve_log 异步 fire-and-forget 日志
- **新增** `pyproject.toml`（uv 包管理） + `.env.example` + `docs/sql/schema.sql`

## Capabilities

### New Capabilities

- `knowledge-base-management`: 知识库创建（name 唯一约束，kb_id 用 nanoid 生成）
- `document-ingestion`: 文档上传 + 同步索引（.md/.txt，≤10MB，SHA-256 去重，heading_aware 切分 + Embedding + pgvector 写入）
- `vector-retrieval`: 纯向量检索（跨 KB 全局 top_k，余弦相似度评分，strict 模式禁止 filter 字段）

### Modified Capabilities

<!-- 无已有 capability，留空 -->

## Impact

- **新增目录**：`domain/`、`application/`、`adapters/`、`tests/`、`docs/sql/`
- **新增依赖**：fastapi、uvicorn、pydantic、pydantic-settings、httpx、asyncpg、pgvector、nanoid + dev（pytest、pytest-asyncio）
- **外部依赖**：PostgreSQL 16 + pgvector 扩展（手动安装，不做 Docker）
- **配置**：`EMBED_API_KEY` 需用户自行提供（通义/Ollama/OpenAI 任一兼容服务）
- **不引入**：LangChain、LlamaIndex、SQLAlchemy、BM25 库、jieba、Docker

> 完整工程规范见 [`docs/3-pgvector-rag-cuddly-dream.md`](../../../docs/3-pgvector-rag-cuddly-dream.md)
```

## openspec/changes/ragnexus-skeleton/design.md

- Source: openspec/changes/ragnexus-skeleton/design.md
- Lines: 1-72
- SHA256: 9a1e7f493d557636937b96a53b65f4672067cbe49c49f8b3e382de90ab692fff

```md
## Context

RAGNexus 从零起步，第一期只做纯向量检索骨架。技术选型与架构已在 `docs/3-pgvector-rag-cuddly-dream.md` 中完整定义。本 design 聚焦关键架构决策和实现约束。

## Goals / Non-Goals

**Goals:**
- 交付 3 个 HTTP API 端点 + pgvector 后端 + 六边形架构骨架
- `git clone` → 手动装 pgvector → `uv pip install -e ".[dev]"` → `pytest` 全过 → `uv run main.py` 起服务
- 为后续 BM25/混合检索/rerank/LLM/异步任务留好扩展点（不改 use case 签名）

**Non-Goals:**
- BM25 / 混合检索 / rerank / LLM 生成
- 异步任务队列（arq/celery）
- 多租户 / 鉴权 / API Key
- 删除接口 / 列表接口
- Docker / docker-compose
- PDF / Word / HTML 解析
- filter 字段实现（接口层禁止传参）
- 监控 / 链路追踪

## Decisions

| # | 决策 | 理由 | 替代方案 |
|---|------|------|----------|
| 1 | **六边形架构**（domain/application/adapters） | 业务代码不依赖外部实现，扩展新向量库/Embedder 只需加 adapter | 分层架构（controller→service→repo）：简单但扩展需改 service 内部 |
| 2 | **Python 3.11 + FastAPI + uv** | 异步友好、自动 OpenAPI、uv 10-100x 快于 pip | Node.js/Go：多一层语言切换成本；Poetry：生态不如 uv 活跃 |
| 3 | **pgvector (HNSW)** 向量索引 | PG 原生，无需额外服务，管理简单 | Milvus/Qdrant：性能更好但运维复杂，推到第二期 |
| 4 | **OpenAI 兼容 Embedder** | 一套实现支持通义/OpenAI/Ollama，切厂商只改 .env | Sentence-Transformers 本地加载：内存占用大，第二期加 adapter |
| 5 | **Google `:` 语法**（`/v1/rag:retrieve`）| 动词在路径中，语义清晰，Google API 设计规范 | RESTful (`GET /v1/rag?…`)：查询参数语义不明确 |
| 6 | **同步索引**（upload 阻塞到写入完成）| 简单，调用方不需要轮询状态 | 异步任务队列：第一期过度设计 |
| 7 | **双字段 KB 重名检测**（name + name_key=lower(trim(name)) + UNIQUE） | 大小写不敏感，应用层友好 | 数据库 UNIQUE(name COLLATE ...)：依赖 PG collation |
| 8 | **heading_aware_split + fixed_size fallback** | .md 按标题结构切，长段落回退固定窗口，保留语义边界 | LangChain RecursiveCharacterTextSplitter：引入重依赖 |
| 9 | **retrieve_log fire-and-forget**（`asyncio.create_task`） | 不阻塞响应，第一期接受丢失风险 | 消息队列写：第二期架构 |

## Risks / Trade-offs

| 风险 | 影响 | 缓解 |
|------|------|------|
| pgvector 需手动安装 | 新人上手门槛 | README 提供 macOS/Ubuntu/Windows 三步安装指南 |
| EMBED_API_KEY 需自备 | 服务不可用 | .env.example 提供三套兼容配置（通义/OpenAI/Ollama） |
| 全局 top_k 跨 KB 偏置 | 大 KB 占满 top_k | 第一期可接受；第二期加 KB 级别限流 |
| `vector(1024)` 维度硬编码 | 改 EMBED_DIM 需 DROP chunks 重建 | 文档注明，schema.sql 加注释警告 |
| retrieve_log 异步可能丢失 | 日志不完整 | 第二期用 task queue 改进 |

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                    adapters/http                      │
│  create_kb_router  upload_doc_router  retrieve_router│
│         │                  │                │         │
├─────────┼──────────────────┼────────────────┼─────────┤
│         ▼                  ▼                ▼         │
│            application (use cases)                    │
│  CreateKnowledgeBase  UploadDocument  Retrieve        │
│         │                  │                │         │
├─────────┼──────────────────┼────────────────┼─────────┤
│         ▼                  ▼                ▼         │
│              domain (ports + models)                  │
│  KnowledgeBasePort  VectorStorePort  EmbedderPort     │
│         │                  │                │         │
├─────────┼──────────────────┼────────────────┼─────────┤
│         ▼                  ▼                ▼         │
│            adapters (implementations)                 │
│  PgKnowledgeBaseRepo  PgVectorStore  OpenAICompatEmb  │
│                            │                          │
│                      PostgreSQL + pgvector            │
└──────────────────────────────────────────────────────┘
```

> 完整代码骨架见 [`docs/3-pgvector-rag-cuddly-dream.md`](../../../docs/3-pgvector-rag-cuddly-dream.md) §3–§8
```

## openspec/changes/ragnexus-skeleton/tasks.md

- Source: openspec/changes/ragnexus-skeleton/tasks.md
- Lines: 1-40
- SHA256: b1efe082327e60bde7ea3d0bdebe195be228fc3e768169866d0514f01b977db6

```md
# Tasks

> 每个任务一个 commit。完整实现细节见 [`docs/3-pgvector-rag-cuddly-dream.md`](../../../docs/3-pgvector-rag-cuddly-dream.md)

## Phase 1 — 脚手架

- [ ] 1. 创建 `pyproject.toml`（依赖 + dev 依赖）、`.env.example`、`.gitignore`、`README.md`、`docs/sql/schema.sql`
- [ ] 2. 创建目录树（`domain/`、`application/`、`adapters/` 子目录）及空白 `__init__.py`
- [ ] 3. 创建 `config.py`（pydantic-settings，20 个配置项）

## Phase 2 — Domain 层

- [ ] 4. `domain/models.py`（6 个 dataclass）+ `domain/chunking.py`（`heading_aware_split` + `fixed_size_split`）
- [ ] 5. `domain/ports.py`（5 个 Protocol）+ `domain/errors.py`（`DomainError` + 11 个子类，带 code + http_status）

## Phase 3 — Application 层

- [ ] 6. `application/create_kb_use_case.py` + `upload_doc_use_case.py` + `retrieve_use_case.py`

## Phase 4 — Adapters 层

- [ ] 7. `adapters/vector_store/pgvector.py`（`PgVectorStore`：connect/close/upsert/search_by_vector）+ `registry.py`
- [ ] 8. `adapters/knowledge_base/pg.py`（`PgKnowledgeBaseRepository`）+ `adapters/retrieve_log/pg.py`（`PgRetrieveLogRepository`）
- [ ] 9. `adapters/embedder/openai_compat.py`（`OpenAICompatEmbedder`：batch/concurrency/retry）+ `adapters/parsers/md_and_txt.py`（`MarkdownAndTextParser`）
- [ ] 10. `adapters/http/`（3 个 router 工厂函数 + `error_handlers.py` 全局 exception_handler）

## Phase 5 — 装配

- [ ] 11. `composition.py`（lifespan 内装配所有依赖并注入路由）+ `main.py`（uvicorn 入口）

## Phase 6 — 测试

- [ ] 12. `tests/unit/`（domain + use case + adapter 单测，mock 全部端口）
- [ ] 13. `tests/integration/`（真实 pgvector + mock embedder）+ `tests/e2e/test_smoke.py`（端到端）

## Phase 7 — 验收

- [ ] 14. 按 §15 验证步骤全量通过：`pytest` 三层全绿、`/docs` 可见 3 接口、curl 三连通、14 项验收清单全覆盖

> 完整工程规范：[`docs/3-pgvector-rag-cuddly-dream.md`](../../../docs/3-pgvector-rag-cuddly-dream.md)
```

## openspec/changes/ragnexus-skeleton/specs/document-ingestion/spec.md

- Source: openspec/changes/ragnexus-skeleton/specs/document-ingestion/spec.md
- Lines: 1-39
- SHA256: 2ca152a35bdbff6ee67956d94853e467661749b2acc41a5a69990e6d29f850a2

```md
# Document Ingestion

## Purpose

提供文档上传 + 同步索引能力，将 .md/.txt 文件解析、切分、向量化后写入 pgvector。

## Requirements

### 文档上传

- **MUST** 接受 `POST /v1/documents:upload`，`multipart/form-data`（`kb_id` + `file`）
- **MUST** 文件大小 ≤ 10MB（超限 → 413，code 1301）
- **MUST** 文件后缀仅 `.md` / `.txt`（其他 → 415，code 1300）
- **MUST** 文件为空或解析无有效内容 → 422（code 1400）
- **MUST** kb_id 不存在 → 404（code 1100）
- **MUST** doc_id 重复（SHA-256 前 16 位）→ 409（code 1201），**在解析/Embedding 前检测**以节省资源

### 文档处理

- **MUST** 同步索引：请求阻塞到所有 chunk 写入 pgvector 才返回
- **MUST** doc_id = `"doc_" + sha256(file_bytes)[:16]`
- **MUST** .md 文件按标题切分（heading_aware_split），长段落回退固定窗口重叠切分（chunk_max_chars=1500, chunk_overlap=50）
- **MUST** .txt 文件固定窗口重叠切分
- **MUST** 过滤空 chunk
- **MUST** Embedding：batch_size=50, max_concurrency=5, 429 重试最多 3 次（指数退避），维度失配 → 502（code 1500）
- **MUST** 事务写入 documents + chunks 表

### 数据模型

- **MUST** `documents` 表：`doc_id PK, kb_id FK, filename, file_hash (完整 SHA-256), file_size, content_type (text/markdown | text/plain), chunk_count, uploaded_at`
- **MUST** `chunks` 表：`PRIMARY KEY (doc_id, id), kb_id FK, doc_id FK, text, metadata JSONB, embedding vector(1024)`
- **MUST** Chunk metadata 包含：`{filename, file_hash, file_size, content_type, chunk_index, heading, heading_level}`

### 响应

- **MUST** 成功返回 201：`{code: 0, data: {doc_id, kb_id, chunk_count}}`
- **MUST NOT** 返回 chunks 列表

> 完整接口规范见 [`docs/3-pgvector-rag-cuddly-dream.md`](../../../../../docs/3-pgvector-rag-cuddly-dream.md) §1.2、§6.2、§8.2、§8.4、§10
```

## openspec/changes/ragnexus-skeleton/specs/knowledge-base-management/spec.md

- Source: openspec/changes/ragnexus-skeleton/specs/knowledge-base-management/spec.md
- Lines: 1-23
- SHA256: bd0bbacb1e95b005f98880d4aca6a9b25b2656fd793b8849bef454ed0d9fb762

```md
# Knowledge Base Management

## Purpose

提供知识库（Knowledge Base）的创建能力，作为文档上传和检索的前置条件。

## Requirements

### KB 创建

- **MUST** 接受 `POST /v1/knowledge-bases:create`，请求体 `{"name": "<1-64 字符>"}`
- **MUST** 返回 `{code: 0, data: {kb_id, name, created_at}}`，`kb_id` 格式 `kb_` + nanoid(8)
- **MUST** 双字段防重名：`name`（用户输入原文）+ `name_key`（`lower(trim(name))` + UNIQUE 约束）
- **MUST** 重名时返回 409（code 1200），`message: "知识库名称已存在"`
- **MUST** name 为空或超长时返回 422（code 1000）
- **MUST** 多余字段 → 422（strict mode）

### 数据模型

- **MUST** 持久化到 `knowledge_bases` 表：`id TEXT PK, name TEXT NOT NULL, name_key TEXT UNIQUE NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW()`
- **MUST** 硬删除策略（第二期加软删除）

> 完整接口规范见 [`docs/3-pgvector-rag-cuddly-dream.md`](../../../../../docs/3-pgvector-rag-cuddly-dream.md) §1.1、§6.1、§10
```

## openspec/changes/ragnexus-skeleton/specs/vector-retrieval/spec.md

- Source: openspec/changes/ragnexus-skeleton/specs/vector-retrieval/spec.md
- Lines: 1-39
- SHA256: 636a775fbd981799bc05cbc3e1b6e61234ed8d78e03e29a6d926b91ce4d3e022

```md
# Vector Retrieval

## Purpose

提供纯向量检索能力，给定查询文本，在指定知识库中检索最相关的文档片段。

## Requirements

### 检索请求

- **MUST** 接受 `POST /v1/rag:retrieve`，请求体 `{"query": "<1-2000 字符>", "kb_ids": ["<1-5 个>"], "top_k": <1-50>}`
- **MUST** strict 模式：多余字段（包括 `filter`）→ 422（code 1000）
- **MUST** kb_ids 任一不存在 → 404（code 1100）
- **MUST** query 为空 / kb_ids 为空 / top_k 越界 → 422（code 1000）

### 检索逻辑

- **MUST** 先 Embedding query → 再向量检索
- **MUST** 评分：余弦相似度 `1 - (embedding <=> query_vector)`，6 位小数，越大越相关
- **MUST** 跨 KB 全局 top_k（不接受 KB 级别偏置的复杂性）
- **MUST** pgvector HNSW 索引（`vector_cosine_ops`）

### 日志

- **MUST** fire-and-forget 写 `retrieve_logs` 表（`asyncio.create_task`，不阻塞响应）
- **MUST** 日志失败被吞掉，不影响主流程
- **MUST** 记录：kb_ids, query, top_k, hit_count, latency_ms

### 响应

- **MUST** 返回 `{code: 0, data: {total, hits: [{chunk_id, kb_id, doc_id, score, text, metadata}]}}`
- **MUST** 空结果返回 `total: 0, hits: []`（非错误）
- **MUST** 错误时返回 code 1501（向量库失败）

### 数据模型

- **MUST** `retrieve_logs` 表：`id BIGSERIAL PK, kb_ids TEXT[], query, top_k, hit_count, latency_ms, created_at`

> 完整接口规范见 [`docs/3-pgvector-rag-cuddly-dream.md`](../../../../../docs/3-pgvector-rag-cuddly-dream.md) §1.3、§6.3、§8.2、§10
```

