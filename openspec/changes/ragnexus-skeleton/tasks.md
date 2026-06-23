# Tasks

> 每个任务一个 commit。完整实现细节见 [`docs/3-pgvector-rag-cuddly-dream.md`](../../../docs/3-pgvector-rag-cuddly-dream.md)

## Phase 1 — 脚手架

- [x] 1. 创建 `pyproject.toml`（依赖 + dev 依赖）、`.env.example`、`.gitignore`、`README.md`、`docs/sql/schema.sql`
- [x] 2. 创建目录树（`domain/`、`application/`、`adapters/` 子目录）及空白 `__init__.py`
- [x] 3. 创建 `config.py`（pydantic-settings，20 个配置项）

## Phase 2 — Domain 层

- [x] 4. `domain/models.py`（6 个 dataclass）+ `domain/chunking.py`（`heading_aware_split` + `fixed_size_split`）
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
