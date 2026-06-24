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
