# Task 3.1 Report — celery_app.py

## Status: ✅ 完成

## 文件
- **新建**: `src/ragnexus/celery_app.py`

## 验证结果

| 检查项 | 结果 |
|--------|------|
| Celery 实例可加载 | ✅ `python -c "from ragnexus.celery_app import app"` |
| broker_url 正确 | ✅ `redis://localhost:6379/0` |
| app.main | ✅ `ragnexus` |
| beat_schedule 包含 monitor-timeout-docs | ✅ task=`ragnexus.tasks.indexing.monitor_timeout_docs`, schedule=300.0s |

## 关键细节
- 使用 `contextlib.suppress(ImportError)` 包裹 `autodiscover_tasks`，因为 `ragnexus.tasks` 包尚未创建（由后续任务完成）
- 配置遵循 Celery 5.x 最佳实践：`task_acks_late` + `worker_prefetch_multiplier=1` 防止任务丢失
- 时区设置为 `Asia/Shanghai`，`enable_utc=True` 遵循 Celery 官方建议
