"""composition — dependency injection container and FastAPI lifespan manager.

Usage::

    from ragnexus.composition import build_app
    app = build_app()  # FastAPI instance with all wiring
"""

from contextlib import asynccontextmanager
import asyncio
from typing import Any, cast

import asyncpg
from fastapi import FastAPI

from ragnexus.adapters.embedder.openai_compat import OpenAICompatEmbedder
from ragnexus.adapters.http.create_kb_router import create_router as create_kb_router
from ragnexus.adapters.http.error_handlers import register_error_handlers
from ragnexus.adapters.http.health_router import create_router as create_health_router
from ragnexus.adapters.http.middleware import LoggingMiddleware
from ragnexus.adapters.http.retrieve_router import (
    create_router as create_retrieve_router,
)
from ragnexus.adapters.http.upload_doc_router import (
    create_router as create_upload_doc_router,
)
from ragnexus.adapters.knowledge_base.pg import PgKnowledgeBaseRepository
from ragnexus.adapters.llm.openai_compatible import OpenAICompatibleLLMProvider
from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser
from ragnexus.adapters.rerank.llm import LLMRerankProvider
from ragnexus.adapters.rerank.noop import NoopRerankProvider
from ragnexus.adapters.retrieve_log.pg import PgRetrieveLogRepository
from ragnexus.adapters.rewrite.llm import LLMRewriteProvider
from ragnexus.adapters.rewrite.noop import NoopRewriteProvider
from ragnexus.adapters.vector_store.pgvector import PgVectorStore
from ragnexus.application.create_kb_use_case import CreateKnowledgeBaseUseCase
from ragnexus.application.retrieve_use_case import RetrieveUseCase
from ragnexus.application.upload_doc_use_case import UploadDocumentUseCase
from ragnexus.config import get_settings
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.core.logger import LoggedPool, logger, setup_logging
from ragnexus.domain.chunking import heading_aware_split
from ragnexus.domain.models import UploadResult
from ragnexus.domain.ports import RerankPort, RewritePort


class CacheInvalidatingUploadUseCase:
    """包装 UploadDocumentUseCase，成功后清空 rerank 和 rewrite 缓存。

    composition.py 的 DI 辅助类 — 对 use case 零侵入。
    NoopRerankProvider/NoopRewriteProvider.clear_cache 为空实现，禁用时无副作用。
    """

    def __init__(
        self,
        inner: UploadDocumentUseCase,
        reranker: RerankPort,
        rewriter: RewritePort,
    ) -> None:
        self._inner = inner
        self._reranker = reranker
        self._rewriter = rewriter

    async def execute(
        self, kb_id: str, file_content: bytes, filename: str, content_type: str
    ) -> UploadResult:
        """执行上传并清空双缓存。"""
        result = await self._inner.execute(
            kb_id=kb_id,
            file_content=file_content,
            filename=filename,
            content_type=content_type,
        )
        # 清空对应 KB 的重排缓存和查询改写缓存
        await self._reranker.clear_cache(kb_id)
        await self._rewriter.clear_cache(kb_id)
        return result


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期 — 注入依赖、运行、清理。

    启动流程:
    1. 加载配置
    2. 配置日志
    3. 创建并连接 PgVectorStore（创建含 pgvector 的 asyncpg 连接池）
    4. 从 pg_catalog 检测 chunks.embedding 维度
    5. 校验 EMBED_DIM 匹配（或 -1 表示无类型向量）
    6. 创建共享仓库连接池
    7. 实例化所有适配器、用例和路由
    8. 注入到 app
    9. yield → 运行
    10. 关闭连接池
    """
    cfg = get_settings()

    # --- Logging -----------------------------------------------------------
    log_listener = setup_logging(cfg)
    app.state.log_listener = log_listener
    # --- 资源追踪（启动阶段抛异常时确保已创建资源被清理）---
    _raw_store_pool = None
    _raw_repo_pool = None
    store = None
    embedder = None
    llm_provider = None

    try:
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

        # --- 4a. 数据库迁移检测 -------------------------------------------------
        try:
            _pending = await repo_pool.fetchval("SELECT count(*) FROM alembic_version")
            if _pending == 0:
                logger.warning("数据库迁移未执行——部署前请运行 'alembic upgrade head'")
        except Exception:
            logger.warning(
                "数据库迁移状态检测失败（alembic_version 表可能不存在）——部署前请运行 'alembic upgrade head'"
            )

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

        # --- LLM Provider（通用大模型调用，被 rerank 共享）---
        llm_provider = OpenAICompatibleLLMProvider(
            base_url=cfg.LLM_BASE_URL,
            api_key=cfg.LLM_API_KEY,
            model=cfg.LLM_MODEL,
            max_concurrency=cfg.LLM_MAX_CONCURRENCY,
            max_retries=cfg.LLM_MAX_RETRIES,
            request_timeout=cfg.LLM_REQUEST_TIMEOUT,
            connect_timeout=cfg.LLM_CONNECT_TIMEOUT,
            retry_backoff_base=cfg.LLM_RETRY_BACKOFF_BASE,
        )

        # --- Rerank Provider ---
        if cfg.RERANK_ENABLED:
            reranker = LLMRerankProvider(
                llm=llm_provider,
                max_candidates=cfg.RERANK_MAX_CANDIDATES,
                chunk_max_chars=cfg.RERANK_CHUNK_MAX_CHARS,
                cache_similarity_threshold=cfg.RERANK_CACHE_SIMILARITY_THRESHOLD,
                cache_max_entries=cfg.RERANK_CACHE_MAX_ENTRIES,
                cache_ttl_seconds=cfg.RERANK_CACHE_TTL_SECONDS,
                temperature=cfg.RERANK_TEMPERATURE,
            )
            candidate_multiplier = cfg.RERANK_CANDIDATE_MULTIPLIER
            min_candidates = cfg.RERANK_MIN_CANDIDATES
        else:
            reranker = NoopRerankProvider()
            candidate_multiplier = 1
            min_candidates = 0
        parser = MarkdownAndTextParser()

        # --- Rewrite Provider ---
        if cfg.REWRITE_ENABLED:
            rewriter = LLMRewriteProvider(
                llm=llm_provider,
                embedder=embedder,
                cache_similarity_threshold=cfg.REWRITE_CACHE_SIMILARITY_THRESHOLD,
                cache_max_entries=cfg.REWRITE_CACHE_MAX_ENTRIES,
                cache_ttl_seconds=cfg.REWRITE_CACHE_TTL_SECONDS,
                temperature=cfg.REWRITE_TEMPERATURE,
            )
        else:
            rewriter = NoopRewriteProvider()
        kb_repo = PgKnowledgeBaseRepository(pool=cast(Any, repo_pool))
        log_repo = PgRetrieveLogRepository(pool=cast(Any, repo_pool))

        # --- 4b. 启动时清理过期检索日志 -----------------------------------------
        _cleanup_tasks: set[asyncio.Task] = set()

        async def _startup_cleanup():
            """启动 5 秒后执行一次清理，不阻塞主流程。"""
            try:
                await asyncio.sleep(5)
                from datetime import datetime, timedelta, timezone

                _deleted = await log_repo.prune(
                    datetime.now(timezone.utc) - timedelta(days=30)
                )
                logger.info("清理过期检索日志: %d 条已删除", _deleted)
            except Exception:
                logger.debug("启动时检索日志清理失败", exc_info=True)

        # 注册 24h 周期清理任务
        async def _periodic_log_cleanup():
            from datetime import datetime, timedelta, timezone

            while True:
                await asyncio.sleep(86400)
                try:
                    await log_repo.prune(
                        datetime.now(timezone.utc) - timedelta(days=30)
                    )
                except Exception:
                    logger.error("周期日志清理失败", exc_info=True)

        # 启动 fire-and-forget 启动清理
        _task = asyncio.create_task(_startup_cleanup())
        _task.add_done_callback(_cleanup_tasks.discard)
        _cleanup_tasks.add(_task)

        # 启动周期任务
        _task = asyncio.create_task(_periodic_log_cleanup())
        _task.add_done_callback(_cleanup_tasks.discard)
        _cleanup_tasks.add(_task)
        app.state._cleanup_tasks = _cleanup_tasks

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

        # 包装 upload_doc_uc，成功后清空 rerank 和 rewrite 缓存
        upload_doc_uc_wrapped = CacheInvalidatingUploadUseCase(
            upload_doc_uc, reranker, rewriter
        )
        retrieve_uc = RetrieveUseCase(
            kb_repo=kb_repo,
            embedder=embedder,
            store=store,
            log_port=log_repo,
            reranker=reranker,
            rewriter=rewriter,
            candidate_multiplier=candidate_multiplier,
            min_candidates=min_candidates,
        )
        # --- 6. Routers -------------------------------------------------------
        app.include_router(create_kb_router(create_kb_uc))
        app.include_router(create_upload_doc_router(upload_doc_uc_wrapped))
        app.include_router(create_retrieve_router(retrieve_uc))
        app.include_router(create_health_router(lambda: store))

        # Stash references for teardown
        app.state.store = store
        app.state.repo_pool = repo_pool

        app.state.retrieve_uc = retrieve_uc
        app.state.upload_doc_uc = upload_doc_uc_wrapped
        yield

    finally:
        # 取消后台清理任务
        cleanup_tasks = getattr(app.state, "_cleanup_tasks", None)
        if cleanup_tasks:
            for t in cleanup_tasks:
                t.cancel()

        # 逆序关闭生命周期资源（llm → embedder → repo_pool → store_pool → log_listener）
        await _shutdown_resources(
            llm_provider=llm_provider,
            embedder=embedder,
            _raw_repo_pool=_raw_repo_pool,
            _raw_store_pool=_raw_store_pool,
            log_listener=log_listener,
        )


async def _shutdown_resources(
    llm_provider: Any | None,
    embedder: Any | None,
    _raw_repo_pool: Any | None,
    _raw_store_pool: Any | None,
    log_listener: Any,
) -> None:
    """逆序关闭生命周期资源（llm → embedder → repo_pool → store_pool → log_listener）。

    每个步骤由嵌套 try/finally 保护，确保前一步抛异常不会阻止后续清理。
    """
    try:
        if llm_provider is not None:
            await llm_provider.close()
    finally:
        try:
            if embedder is not None:
                await embedder.close()
        finally:
            try:
                if _raw_repo_pool is not None:
                    await _raw_repo_pool.close()
            finally:
                try:
                    if _raw_store_pool is not None:
                        await _raw_store_pool.close()
                finally:
                    log_listener.stop()


def build_app() -> FastAPI:
    """返回完全装配的 FastAPI 应用。

    lifespan 上下文管理器处理启动（DI 注入）和关闭（连接池清理）。
    构造时不需要外部依赖 — app 可安全导入，无需运行中的数据库。
    """
    app = FastAPI(lifespan=lifespan)
    register_error_handlers(app)
    app.add_middleware(LoggingMiddleware)
    app.middleware_stack = app.build_middleware_stack()
    return app
