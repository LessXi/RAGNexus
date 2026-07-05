# Task 3.3 Report — Celery tasks 模块

## Status: ✅ 完成

## 文件

| 文件 | 操作 |
|------|------|
| `src/ragnexus/tasks/__init__.py` | 新建 (1 行) |
| `src/ragnexus/tasks/indexing.py` | 新建 (69 行) |

## 包含组件

| 组件 | 说明 |
|------|------|
| `index_document_task` | Celery 任务，`asyncio.run` 桥接到 `IndexingService.execute`，带自动重试 |
| `monitor_timeout_docs` | Celery Beat 周期任务，将超时 PROCESSING 文档标记为 FAILED |

## 验证结果

| 检查项 | 结果 |
|--------|------|
| 模块导入 | ✅ `python -c "from ragnexus.tasks.indexing import index_document_task, monitor_timeout_docs"` |
| Ruff check | ✅ OK (0 errors) |
| Ruff format | ✅ 无变更 |
| Commit | ✅ `5a99ecc feat(async): Celery tasks — index_document + monitor_timeout_docs` |

## 已知依赖

| 依赖 | 状态 |
|------|------|
| `ragnexus.di.build_indexing_services` | ⚠️ 尚未创建（预计由 Task 28 完成）。延迟导入在函数体内，不影响模块加载，仅运行时依赖 |
| `ragnexus.celery_app.app` (beat_schedule) | ✅ 已配置 `monitor-timeout-docs` 每 5 分钟执行 |

## 关键设计细节

### index_document_task
- **`bind=True`** + `max_retries=2` → Celery 重试语义，`self.retry(exc=exc) from exc` 保持异常链
- **延迟导入** `build_indexing_services`：避免模块加载时循环依赖，确保 Worker 进程启动后再装配
- 解包返回值 `indexing_svc, doc_repo, kb_repo` 为后续扩展（同义词同步等）预留接口

### monitor_timeout_docs
- 独立创建 `asyncpg.Pool(min_size=1, max_size=2)` — Beat 进程不共享 API 进程的连接池
- `DocStatus.PROCESSING.value` / `DocStatus.FAILED.value` 直接使用 IntEnum 值，避免魔术数字
- 仅在 `count > 0` 时记录 warning 日志，避免噪音
