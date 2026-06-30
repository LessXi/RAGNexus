"""健康检查端点 — GET /health。

提供 DB 连接池可达性检查，
以及系统元信息（版本、运行时间、Python 版本）。
"""

import asyncio
import sys
import time
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ragnexus import __version__
from ragnexus.core.logger import logger

_start_time: float = time.time()


def create_router(get_store) -> APIRouter:
    """工厂函数：返回含 GET /health 端点的 APIRouter。

    参数：
        get_store: 可调用，返回 PgVectorStore 实例（需有 .pool）
    """

    router = APIRouter(tags=["health"])

    @router.get("/health")
    async def health():
        checks: dict[str, str] = {}

        # 数据库检查：SELECT 1（3s 超时）
        try:
            store = get_store()
            await asyncio.wait_for(
                store.pool.fetchval("SELECT 1"),
                timeout=3.0,
            )
            checks["database"] = "ok"
        except Exception as exc:
            logger.warning("健康检查 DB 探测失败: %s", exc)
            checks["database"] = "error"

        status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
        http_status = 200 if status == "ok" else 503

        return JSONResponse(
            status_code=http_status,
            content={
                "status": status,
                "checks": checks,
                "version": __version__,
                "timestamp": datetime.now(UTC).isoformat(),
                "uptime_seconds": int(time.time() - _start_time),
                "python_version": sys.version.split()[0],
            },
        )

    return router
