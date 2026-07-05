"""索引相关 Celery 任务 — index_document + timeout monitor。"""

import asyncio
from datetime import UTC, datetime, timedelta

import asyncpg

from ragnexus.celery_app import app
from ragnexus.config import get_settings
from ragnexus.core.logger import logger
from ragnexus.domain.models import DocStatus


@app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    autoretry_for=(Exception,),
)
def index_document_task(self, doc_id: str) -> None:
    """Celery 任务入口 — asyncio.run 桥接到 IndexingService.execute。"""
    from ragnexus.di import build_indexing_services

    indexing_svc, doc_repo, kb_repo = build_indexing_services()

    try:
        asyncio.run(indexing_svc.execute(doc_id))
    except Exception as exc:
        logger.warning(
            "索引任务重试",
            extra={"doc_id": doc_id, "retry": self.request.retries, "error": str(exc)},
        )
        raise self.retry(exc=exc) from exc


@app.task(name="ragnexus.tasks.indexing.monitor_timeout_docs")
def monitor_timeout_docs() -> None:
    """Celery Beat 周期任务 — 将超时的 PROCESSING 文档标记为 FAILED。"""
    settings = get_settings()
    timeout = timedelta(minutes=settings.INDEX_TIMEOUT_MINUTES)
    cutoff = datetime.now(UTC) - timeout

    async def _run():
        pool = await asyncpg.create_pool(settings.PG_DSN, min_size=1, max_size=2)
        try:
            result = await pool.execute(
                "UPDATE documents SET status = $1, error_message = $2, updated_at = $3 "
                "WHERE status = $4 AND updated_at < $5",
                DocStatus.FAILED.value,
                "索引超时（Worker 可能崩溃）",
                datetime.now(UTC),
                DocStatus.PROCESSING.value,
                cutoff,
            )
            count = int(result.split()[-1]) if result else 0
            if count > 0:
                logger.warning(
                    "超时文档标记为 FAILED",
                    extra={
                        "event_type": "BIZ_EVENT",
                        "event": "timeout_docs_failed",
                        "count": count,
                        "cutoff": cutoff.isoformat(),
                    },
                )
        finally:
            await pool.close()

    asyncio.run(_run())
