"""Shared DI factory — build_indexing_services(cfg) 供 API 和 Worker 复用。"""

from typing import Any, cast

import asyncpg

from ragnexus.adapters.document.pg import PgDocumentRepository
from ragnexus.adapters.embedder.openai_compat import OpenAICompatEmbedder
from ragnexus.adapters.keyword_search.elasticsearch import ESKeywordSearchProvider
from ragnexus.adapters.knowledge_base.pg import PgKnowledgeBaseRepository
from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser
from ragnexus.adapters.vector_store.pgvector import PgVectorStore
from ragnexus.application.indexing_service import IndexingService
from ragnexus.config import Settings, get_settings
from ragnexus.core.logger import LoggedPool


async def _async_build_services(cfg: Settings):
    """异步构建 IndexingService 及其所有依赖 — 共享的 async 构建器。"""
    store_pool = await asyncpg.create_pool(
        cfg.PG_DSN, min_size=1, max_size=3, command_timeout=cfg.PG_COMMAND_TIMEOUT
    )
    store = PgVectorStore(
        dsn=cfg.PG_DSN, pool_min=1, pool_max=3, command_timeout=cfg.PG_COMMAND_TIMEOUT
    )
    await store.connect(external_pool=LoggedPool(store_pool))

    repo_pool = await asyncpg.create_pool(
        cfg.PG_DSN, min_size=1, max_size=3, command_timeout=cfg.PG_COMMAND_TIMEOUT
    )
    logged_repo_pool = LoggedPool(repo_pool)
    kb_repo = PgKnowledgeBaseRepository(pool=cast(Any, logged_repo_pool))
    doc_repo = PgDocumentRepository(pool=cast(Any, logged_repo_pool))
    parser = MarkdownAndTextParser()
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

    keyword_store = None
    if cfg.ES_ENABLED:
        keyword_store = ESKeywordSearchProvider(
            url=cfg.ELASTICSEARCH_URL,
            index=cfg.ELASTICSEARCH_INDEX,
            request_timeout=cfg.ELASTICSEARCH_REQUEST_TIMEOUT,
        )
        try:
            await keyword_store.connect()
            await keyword_store.ensure_index()
        except Exception:
            keyword_store = None

    indexing_svc = IndexingService(
        doc_repo=doc_repo,
        parser=parser,
        embedder=embedder,
        chunker=None,  # IndexingService 内部按扩展名自行分流
        store=store,
        keyword_store=keyword_store,
        es_enabled=cfg.ES_ENABLED,
        chunk_max_chars=cfg.CHUNK_MAX_CHARS,
        chunk_overlap=cfg.CHUNK_OVERLAP,
        table_max_rows_per_chunk=cfg.TABLE_MAX_ROWS_PER_CHUNK,
    )
    indexing_svc._repo_pool = repo_pool  # type: ignore[attr-defined]
    return indexing_svc, doc_repo, kb_repo


def build_indexing_services(cfg: Settings | None = None):
    """构建 IndexingService 及其依赖 — 供 Worker task 使用。

    注意：内部调用 asyncio.run()，会关闭 event loop。
    如果需要在同一 loop 中构建+执行，请使用 build_indexing_services_async()。
    """
    import asyncio

    if cfg is None:
        cfg = get_settings()
    return asyncio.run(_async_build_services(cfg))


async def build_indexing_services_async(cfg: Settings | None = None):
    """异步构建 IndexingService — 供需要在同一 event loop 中构建+执行的场景使用。

    Celery Worker 任务应使用此函数，以便在单个 asyncio.run() 中完成构建→执行→清理。
    """
    if cfg is None:
        cfg = get_settings()
    return await _async_build_services(cfg)
