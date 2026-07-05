"""Celery 应用实例 — 供 Worker 和 Beat 进程使用。"""

import contextlib

from celery import Celery

from ragnexus.config import get_settings

settings = get_settings()

app = Celery("ragnexus")
app.config_from_object(
    {
        "broker_url": settings.CELERY_BROKER_URL,
        "result_backend": settings.CELERY_RESULT_BACKEND,
        "task_serializer": "json",
        "result_serializer": "json",
        "accept_content": ["json"],
        "timezone": "Asia/Shanghai",
        "enable_utc": True,
        "task_track_started": True,
        "task_acks_late": True,
        "worker_prefetch_multiplier": 1,
        "beat_schedule": {
            "monitor-timeout-docs": {
                "task": "ragnexus.tasks.indexing.monitor_timeout_docs",
                "schedule": 300.0,  # 每 5 分钟
            },
        },
    }
)

# 自动发现 tasks 模块。一旦 ragnexus.tasks 包创建后，移除 contextlib.suppress。
with contextlib.suppress(ImportError):
    app.autodiscover_tasks(["ragnexus.tasks"])
