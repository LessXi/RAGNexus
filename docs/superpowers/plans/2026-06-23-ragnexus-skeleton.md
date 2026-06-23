---
change: ragnexus-skeleton
design-doc: docs/superpowers/specs/2026-06-23-ragnexus-skeleton-design.md
base-ref: 84e91291aca706876541454e2520973df10fe107
---

# RAGNexus 第一期骨架 — 实施计划

**Goal:** 交付 3 个 HTTP API + pgvector + OpenAI 兼容 Embedder + 六边形架构 + 三层测试。

**Architecture:** domain → application → adapters。Python 3.11 + FastAPI + asyncpg + pgvector + uv。

**Tech Stack:** fastapi, uvicorn, pydantic v2, pydantic-settings, httpx, asyncpg, pgvector, nanoid + dev(pytest, pytest-asyncio)

## Global Constraints

- Python 3.11+, uv 包管理
- 六边形架构：domain/ 不 import adapters/
- snake_case 字段，ISO 8601 时间
- 响应格式 `{code, data, message, errors?}`，strict mode（pydantic extra="forbid"）
- 20 个 .env 配置项全部由 composition.py 注入
- EMBED_DIM 启动检测（pg_attribute.atttypmod 查询 chunks.embedding 列维度）（ConfigError 1600），Docker Compose 一键拉起（推荐）
- 同步索引，硬删除，全有或全无 embedder 批次失败

---

## Phase 1 — 脚手架

### Task 1: pyproject.toml + .env.example + .gitignore + docs/sql/schema.sql + README

**Files:** Create: `pyproject.toml`, `.env.example`, `.gitignore`, `docs/sql/schema.sql`, `README.md`

**Produces:** 项目依赖声明、20 个 env 配置项、4 张表 pgvector schema

- [ ] 创建 pyproject.toml（fastapi, uvicorn, pydantic, httpx, asyncpg, pgvector, nanoid）
- [ ] 创建 .env.example（全部 20 项：HOST, PORT, LOG_LEVEL, PG_DSN, PG_POOL_MIN/MAX, PG_COMMAND_TIMEOUT, EMBED_* × 8, CHUNK_MAX_CHARS, CHUNK_OVERLAP, MAX_FILE_SIZE）
- [ ] 创建 .gitignore（.venv, __pycache__, .env, .pytest_cache）
- [ ] 创建 docs/sql/schema.sql（knowledge_bases, documents, chunks+hnsw, retrieve_logs，全部 IF NOT EXISTS）
- [ ] 创建 README.md（Docker Compose 快速开始 + 手动安装 + curl 三连示例）
- [ ] `uv pip install -e ".[dev]"` → 无报错
- [ ] Commit: `git add ... && git commit -m "feat: add project scaffold"`

### Task 2: 目录树 + __init__.py

**Files:** Create: `domain/`, `application/`, `adapters/{http,vector_store,knowledge_base,embedder,parsers,retrieve_log}/`, `tests/{unit/{domain,application,adapters},integration,e2e}/` — 全部含 `__init__.py`

- [ ] 创建全部目录和空白 `__init__.py`
- [ ] `python -c "import domain; import application; import adapters; print('OK')"` → `OK`
- [ ] Commit

### Task 3: config.py（pydantic-settings，20 配置项）

**Files:** Create: `config.py`; Test: `tests/unit/test_config.py`

- [ ] Red: 写测试 — `test_defaults` 验证 HOST=0.0.0.0, EMBED_DIM=1024, MAX_FILE_SIZE=10MB; `test_get_settings_is_singleton` 验证 lru_cache
- [ ] Green: 实现 `Settings(BaseSettings)` 20 字段 + `@lru_cache get_settings()`
- [ ] 运行 `uv run pytest tests/unit/test_config.py -v` → PASS
- [ ] Commit

---

## Phase 2 — Domain 层

### Task 4: domain/models.py（6 dataclass）+ domain/chunking.py

**Files:** Create: `domain/models.py`, `domain/chunking.py`; Test: `tests/unit/domain/`

- [ ] Red: 写 test_models.py — `test_knowledge_base_creation`, `test_chunk_id_format`(doc_id:index), `test_searchhit_score_is_float`
- [ ] Red: 写 test_chunking.py — `test_heading_aware_split`(带#标题的md), `test_fixed_size_split`(纯文本), `test_empty_input`, `test_overlap`
- [ ] Green: 实现 6 个 dataclass（KnowledgeBase, Section, ParsedDocument, Chunk, SearchHit, UploadResult）
- [ ] Green: 实现 `heading_aware_split(parsed, max_chars, overlap)` + `fixed_size_split(text, max_chars, overlap)` — 单段超长回退固定窗口重叠切分
- [ ] `uv run pytest tests/unit/domain/ -v` → PASS
- [ ] Commit

### Task 5: domain/ports.py（5 Protocol）+ domain/errors.py（DomainError + 11 子类）

**Files:** Create: `domain/ports.py`, `domain/errors.py`; Test: `tests/unit/domain/`

- [ ] Red: 写 test_errors.py — `test_error_codes`(ValidationError=1000, NotFoundError=1100, ConflictError=1200, DuplicateDocumentError=1201, UnsupportedMediaTypeError=1300, PayloadTooLargeError=1301, EmptyFileError=1400, UpstreamError=1500, VectorStoreError=1501, ConfigError=1600), `test_http_status`, `test_error_fields`
- [ ] Green: 实现 DomainError 基类 + 11 子类（每个带 code + http_status + message 类属性）
- [ ] Green: 实现 5 个 Protocol：VectorStorePort, KnowledgeBasePort, EmbedderPort, ParserPort, RetrieveLogPort
- [ ] `uv run pytest tests/unit/domain/ -v` → PASS
- [ ] Commit

---

## Phase 3 — Application 层

### Task 6: application/create_kb_use_case.py

**Files:** Create: `application/create_kb_use_case.py`; Test: `tests/unit/application/test_create_kb.py`

- [ ] Red: mock KnowledgeBasePort — `test_create_kb_success`(返回 KnowledgeBase), `test_name_too_short/too_long`(ValidationError), `test_duplicate_name`(ConflictError, name_key 冲突)
- [ ] Green: 实现 `CreateKnowledgeBaseUseCase.execute(name: str)` — strip + 1-64 校验 + name_key = lower(name) + repo.create(name, name_key)
- [ ] `uv run pytest tests/unit/application/test_create_kb.py -v` → PASS
- [ ] Commit

### Task 7: application/upload_doc_use_case.py

**Files:** Create: `application/upload_doc_use_case.py`; Test: `tests/unit/application/test_upload_doc.py`

- [ ] Red: mock 全部端口 — `test_upload_success`(返回 UploadResult), `test_file_too_large`(413), `test_wrong_extension`(415), `test_kb_not_found`(404), `test_duplicate_doc`(doc_exists → 409, **在解析前检测**), `test_empty_file`(422)
- [ ] Green: 实现 `UploadDocumentUseCase.execute` — 文件大小/类型/KB存在/doc_id+查重/解析+切分（传 max_chars + overlap）/embedding + 重试/构造 chunks + common_meta（filename, file_hash, file_size, content_type）/事务 upsert（全有或全无）
- [ ] `uv run pytest tests/unit/application/test_upload_doc.py -v` → PASS
- [ ] Commit

### Task 8: application/retrieve_use_case.py

**Files:** Create: `application/retrieve_use_case.py`; Test: `tests/unit/application/test_retrieve.py`

- [ ] Red: mock 全部端口 — `test_retrieve_success`(返回 hits[]), `test_query_empty/kb_ids_empty/top_k_oob`(422), `test_kb_not_found`(404), `test_retrieve_log_fire_and_forget`（日志异步写，失败不影响响应）
- [ ] Green: 实现 `RetrieveUseCase.execute` — 校验 query/kb_ids/top_k → 逐个确认 KB 存在 → embedder.embed([query]) → store.search_by_vector → finally: asyncio.create_task(log_port.log) 吞异常
- [ ] `uv run pytest tests/unit/application/test_retrieve.py -v` → PASS
- [ ] Commit

---

## Phase 4 — Adapters 层

### Task 9: adapters/embedder/openai_compat.py

**Files:** Create: `adapters/embedder/openai_compat.py`; Test: `tests/unit/adapters/test_embedder.py`

- [ ] Red: mock httpx — `test_embed_single_batch`(返回 vectors), `test_embed_multiple_batches`(batch=2, 验证并发), `test_429_retry`(第1次429→重试→成功), `test_max_retries_exhausted`(3次都失败→UpstreamError), `test_dimension_mismatch`(返回维度!=EMBED_DIM→RuntimeError)
- [ ] Green: 实现 `OpenAICompatEmbedder` — __init__ 10参数（base_url, api_key, model, dim, batch_size, max_concurrency, max_retries, request_timeout, connect_timeout, retry_backoff_base），_ensure_client 用 httpx.Timeout，embed 用 asyncio.gather + Semaphore + 指数退避重试
- [ ] `uv run pytest tests/unit/adapters/test_embedder.py -v` → PASS
- [ ] Commit

### Task 10: adapters/vector_store/pgvector.py

**Files:** Create: `adapters/vector_store/pgvector.py`, `adapters/vector_store/registry.py`; Test: `tests/unit/adapters/test_vector_store.py`

- [ ] Red: mock asyncpg — `test_upsert_new_doc`(INSERT document + chunks), `test_upsert_duplicate_doc`(DuplicateDocumentError 1201), `test_search_by_vector`(返回 SearchHit[] 按 score 排序)
- [ ] Green: 实现 `PgVectorStore` — connect/close 管理 asyncpg pool（register_vector, command_timeout=cfg.PG_COMMAND_TIMEOUT），upsert（查重 + INSERT documents + executemany chunks 在同一事务），search_by_vector（HNSW <=> 排序 + 1-distance 分数 + LIMIT）
- [ ] Green: registry.py — 导出 PgVectorStore
- [ ] `uv run pytest tests/unit/adapters/test_vector_store.py -v` → PASS
- [ ] Commit

### Task 11: adapters/knowledge_base/pg.py + adapters/retrieve_log/pg.py + adapters/parsers/md_and_txt.py

**Files:** Create: `adapters/knowledge_base/pg.py`, `adapters/retrieve_log/pg.py`, `adapters/parsers/md_and_txt.py`; Test: 对应 test 文件

- [ ] `PgKnowledgeBaseRepository`: create(nanoid kb_id + UNIQUE name_key → ConflictError), get, exists, doc_exists(SELECT documents)
- [ ] `PgRetrieveLogRepository`: log(fire-and-forget INSERT retrieve_logs, 不返回结果)
- [ ] `MarkdownAndTextParser`: parse .md（heading-aware 解析 → Section 列表，无标题时 raw_text）; parse .txt（直接 raw_text）
- [ ] 全部单测 `uv run pytest tests/unit/adapters/ -v` → PASS
- [ ] Commit

---

## Phase 5 — HTTP + 装配

### Task 12: adapters/http/（3 router + error_handlers）

**Files:** Create: `adapters/http/create_kb_router.py`, `adapters/http/upload_doc_router.py`, `adapters/http/retrieve_router.py`, `adapters/http/error_handlers.py`; Test: `tests/unit/adapters/test_http.py`

- [ ] 实现工厂函数 router 模式（`def create_router(uc: UseCase) -> APIRouter`），每个 router 使用 pydantic BaseModel（strict `extra="forbid"`）
- [ ] error_handlers.py: `register_error_handlers(app)` → `@app.exception_handler(DomainError)` → JSONResponse(code, data: null, message, errors)
- [ ] 单测 mock use case → 验证请求校验（name 长度/query 空/kb_ids 空/多余字段→422）和响应格式
- [ ] Commit

### Task 13: composition.py + main.py

**Files:** Create: `composition.py`, `main.py`

- [ ] composition.py: `@asynccontextmanager lifespan(app)` — get_settings → PgVectorStore + logging.basicConfig + EMBED_DIM 启动检测（pg_attribute.atttypmod 查询 chunks.embedding 列维度） → connect → 装配所有依赖 → 注入 routers → yield → close
- [ ] main.py: `get_settings()` → `uvicorn.run("composition:build_app", factory=True, host=cfg.HOST, port=cfg.PORT)`
- [ ] Commit

---

## Phase 6 — 测试 + 验收

### Task 14: 集成测试 + E2E + 验收

**Files:** Create: `tests/integration/*.py`, `tests/e2e/test_smoke.py`; Modify: `tests/integration/conftest.py`

- [ ] tests/integration/conftest.py: session-scoped fixture — 启动 test-db（docker compose -f docker-compose.test.yml up -d），建表，yield，teardown 清理
- [ ] test_pg_vector_store.py: 真实 pgvector 测试 upsert + search_by_vector + 查重
- [ ] test_pg_kb_repo.py: 真实 PG 测试 create + get + exists + doc_exists
- [ ] test_documents_table.py: 真实 PG 测试 documents INSERT + FK cascade
- [ ] test_retrieve_log.py: 真实 PG 测试 log INSERT + 异步写入
- [ ] tests/e2e/test_smoke.py: 启动 app → TestClient → curl 三连（创建 KB → 上传 .md → 检索） + 错误场景（409/404/415/413/422）
- [ ] `uv run pytest -v` → 全部通过
- [ ] Commit


## Self-Review

**Spec coverage**: 所有 3 个 capability spec 的 MUST 需求均有对应任务：
- knowledge-base-management → Tasks 6, 11
- document-ingestion → Tasks 7, 9, 10, 11
- vector-retrieval → Tasks 8, 9, 10

**No placeholders**: 全部任务含确定性文件路径、命令和预期输出。无 TBD/TODO。

**Type consistency**:
- KnowledgeBase(id:str, name:str, created_at:datetime) — 定义于 Task 4，Task 6/11 消费
- Chunk(id:str="{doc_id}:{index}", kb_id:str, doc_id:str, text:str, vector:list[float], metadata:dict) — Task 4 定义，Task 7/10 消费
- SearchHit(chunk_id, kb_id, doc_id, score:float, text, metadata) — Task 4 定义，Task 8/10 消费
- UploadResult(doc_id, kb_id, chunks:list[Chunk]) — Task 4 定义，Task 7 消费
- ConfigError(code=1600, http_status=500) — Task 5 定义，Task 13 消费
