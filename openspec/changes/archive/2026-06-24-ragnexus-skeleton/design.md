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
