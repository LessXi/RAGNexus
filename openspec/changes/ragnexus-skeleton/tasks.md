# Tasks

> 每个任务一个 commit。完整实现细节见 [`docs/3-pgvector-rag-cuddly-dream.md`](../../../docs/3-pgvector-rag-cuddly-dream.md)

## Phase 1 — 脚手架

- [x] 1. 创建 pyproject.toml + .env.example + .gitignore + README + schema.sql
- [x] 2. 创建目录树 + __init__.py
- [x] 3. 创建 config.py（pydantic-settings，20 配置项）

## Phase 2 — Domain 层

- [x] 4. domain/models.py（6 个 dataclass）+ domain/chunking.py
- [x] 5. domain/ports.py（5 Protocol）+ domain/errors.py（DomainError + 子类）

## Phase 3 — Application 层

- [x] 6. application/create_kb_use_case.py
- [x] 7. application/upload_doc_use_case.py
- [x] 8. application/retrieve_use_case.py

## Phase 4 — Adapters 层

- [x] 9. adapters/embedder/openai_compat.py
- [x] 10. adapters/vector_store/pgvector.py + registry.py
- [x] 11. adapters/knowledge_base/pg.py + retrieve_log/pg.py + parsers/md_and_txt.py
- [ ] 12. adapters/http/（3 router + error_handlers）

## Phase 5 — 装配

- [ ] 13. composition.py + main.py

## Phase 6 — 测试

- [ ] 14. 集成测试 + E2E + 验收

> 完整工程规范：[`docs/3-pgvector-rag-cuddly-dream.md`](../../../docs/3-pgvector-rag-cuddly-dream.md)
