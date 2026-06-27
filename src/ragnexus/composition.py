"""composition — dependency injection container and FastAPI lifespan manager.

Usage::

    from ragnexus.composition import build_app
    app = build_app()  # FastAPI instance with all wiring
"""

from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI

from ragnexus.adapters.embedder.openai_compat import OpenAICompatEmbedder
from ragnexus.adapters.http.create_kb_router import create_router as create_kb_router
from ragnexus.adapters.http.error_handlers import register_error_handlers
from ragnexus.adapters.http.middleware import LoggingMiddleware
from ragnexus.adapters.http.retrieve_router import (
    create_router as create_retrieve_router,
)
from ragnexus.adapters.http.upload_doc_router import (
    create_router as create_upload_doc_router,
)
from ragnexus.adapters.knowledge_base.pg import PgKnowledgeBaseRepository
from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser
from ragnexus.adapters.retrieve_log.pg import PgRetrieveLogRepository
from ragnexus.adapters.vector_store.pgvector import PgVectorStore
from ragnexus.application.create_kb_use_case import CreateKnowledgeBaseUseCase
from ragnexus.application.retrieve_use_case import RetrieveUseCase
from ragnexus.application.upload_doc_use_case import UploadDocumentUseCase
from ragnexus.config import get_settings
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.core.logger import LoggedPool, setup_logging
from ragnexus.domain.chunking import heading_aware_split


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — wire dependencies, yield, tear down.

    Startup sequence:
    1. Load settings
    2. Configure logging
    3. Create and connect PgVectorStore (creates asyncpg pool with pgvector)
    4. Detect chunks.embedding dimension from pg_catalog
    5. Validate EMBED_DIM matches (or is -1 for untyped vector)
    6. Create shared repository pool
    7. Instantiate all adapters, use cases, and routers
    8. Inject into app
    9. yield → serve
    10. Close pools
    """
    cfg = get_settings()

    # --- Logging -----------------------------------------------------------
    log_listener = setup_logging(cfg)
    app.state.log_listener = log_listener

    # --- 1. Vector store (external pool wrapped with LoggedPool) ----------
    _raw_store_pool = await asyncpg.create_pool(
        cfg.PG_DSN,
        min_size=cfg.PG_POOL_MIN,
        max_size=cfg.PG_POOL_MAX,
        command_timeout=cfg.PG_COMMAND_TIMEOUT,
    )
    store = PgVectorStore(
        dsn=cfg.PG_DSN,
        pool_min=cfg.PG_POOL_MIN,
        pool_max=cfg.PG_POOL_MAX,
        command_timeout=cfg.PG_COMMAND_TIMEOUT,
    )
    await store.connect(external_pool=LoggedPool(_raw_store_pool))

    # --- 2. EMBED_DIM validation ------------------------------------------
    if store.pool is None:
        raise AppError(ErrorCode.CONFIG_ERROR, "向量库连接池未初始化")
    try:
        actual_dim: int | None = await store.pool.fetchval(
            "SELECT atttypmod FROM pg_attribute a"
            " JOIN pg_class c ON c.oid = a.attrelid"
            " WHERE c.relname = 'chunks'"
            " AND a.attname = 'embedding'",
        )
    except Exception as exc:
        raise AppError(
            ErrorCode.CONFIG_ERROR,
            "无法检测 embedding 列维度——请确保 schema.sql 已执行且数据库可访问",
            errors=[{"field": "embedding", "reason": str(exc)}],
        ) from exc

    if actual_dim is None:
        raise AppError(
            ErrorCode.CONFIG_ERROR,
            "chunks.embedding 列不存在——请先执行 docs/sql/schema.sql",
            errors=[{"field": "embedding", "reason": "列未找到"}],
        )
    if actual_dim not in (-1, cfg.EMBED_DIM):
        raise AppError(
            ErrorCode.CONFIG_ERROR,
            f"EMBED_DIM 不匹配：数据库 chunks.embedding 为 vector({actual_dim})，"
            f"配置为 {cfg.EMBED_DIM}",
            errors=[
                {
                    "field": "EMBED_DIM",
                    "reason": f"数据库维度为 {actual_dim}",
                },
            ],
        )

    # --- 3. Shared repository pool (KB metadata + retrieve log) -----------
    _raw_repo_pool = await asyncpg.create_pool(
        cfg.PG_DSN,
        min_size=cfg.PG_POOL_MIN,
        max_size=cfg.PG_POOL_MAX,
        command_timeout=cfg.PG_COMMAND_TIMEOUT,
    )
    repo_pool = LoggedPool(_raw_repo_pool)

    # --- 4. Adapters ------------------------------------------------------
    embedder = OpenAICompatEmbedder(
        base_url=cfg.EMBED_BASE_URL,
        api_key=cfg.EMBED_API_KEY,
        model=cfg.EMBED_MODEL,
        dim=cfg.EMBED_DIM,
        batch_size=cfg.EMBED_BATCH_SIZE,
        max_concurrency=cfg.EMBED_MAX_CONCURRENCY,
        max_retries=cfg.EMBED_MAX_RETRIES,
        request_timeout=cfg.EMBED_REQUEST_TIMEOUT,
        connect_timeout=cfg.EMBED_CONNECT_TIMEOUT,
        retry_backoff_base=cfg.EMBED_RETRY_BACKOFF_BASE,
    )
    parser = MarkdownAndTextParser()
    kb_repo = PgKnowledgeBaseRepository(pool=repo_pool)  # type: ignore[arg-type]
    log_repo = PgRetrieveLogRepository(pool=repo_pool)  # type: ignore[arg-type]

    # Chunker: pass raw function so use case controls max_chars/overlap
    chunker = heading_aware_split

    # --- 5. Use cases -----------------------------------------------------
    create_kb_uc = CreateKnowledgeBaseUseCase(kb_repo=kb_repo)
    upload_doc_uc = UploadDocumentUseCase(
        kb_repo=kb_repo,
        parser=parser,
        embedder=embedder,
        chunker=chunker,
        store=store,
        max_file_size=cfg.MAX_FILE_SIZE,
        chunk_max_chars=cfg.CHUNK_MAX_CHARS,
        chunk_overlap=cfg.CHUNK_OVERLAP,
    )
    retrieve_uc = RetrieveUseCase(
        kb_repo=kb_repo,
        embedder=embedder,
        store=store,
        log_port=log_repo,
    )

    # --- 6. Routers -------------------------------------------------------
    app.include_router(create_kb_router(create_kb_uc))
    app.include_router(create_upload_doc_router(upload_doc_uc))
    app.include_router(create_retrieve_router(retrieve_uc))

    # Stash references for teardown
    app.state.store = store
    app.state.repo_pool = repo_pool

    yield

    # --- 7. Teardown ------------------------------------------------------
    # 用 try/finally 确保每个资源都会被清理，即使前置步骤抛出异常
    try:
        await store.close()
    finally:
        try:
            await _raw_store_pool.close()
        finally:
            try:
                await _raw_repo_pool.close()
            finally:
                app.state.log_listener.stop()


def build_app() -> FastAPI:
    """Return a fully-wired FastAPI application.

    The lifespan context manager handles startup (DI wiring) and shutdown
    (pool cleanup).  No external dependencies are required at construction
    time — the app is safe to import without a running database.
    """
    app = FastAPI(lifespan=lifespan)
    register_error_handlers(app)
    app.add_middleware(LoggingMiddleware)
    app.middleware_stack = app.build_middleware_stack()
    return app
