# Task 3.2 Report — indexing_service.py

## Status: ✅ 完成

## 文件
- **新建**: `src/ragnexus/application/indexing_service.py` (195 行)

## 包含组件

| 组件 | 说明 |
|------|------|
| `IndexingService` | 异步索引流水线：解析→分块→嵌入→双写→状态更新 |
| `purge_document_chunks()` | 协调函数：ES `delete_by_document` + PG CASCADE 自动清理 |

## 验证结果

| 检查项 | 结果 |
|--------|------|
| 模块导入 | ✅ `python -c "from ragnexus.application.indexing_service import IndexingService, purge_document_chunks"` |
| 无未使用 import | ✅ (ruff F401) |
| 类型注解风格 | ✅ (ruff UP037) |

## 关键设计细节

### IndexingService
- **幂等保护**: 非 `DocStatus.PROCESSING` 的文档直接跳过，防止 Celery 重试时重复索引
- **双写事务**: 完全复用 `upload_doc_use_case.py` 的事务模式 — `asyncio.ensure_future` 并发 PG + ES，按四种结果组合处理 commit/rollback/orphan cleanup
- **ES 降级**: `es_enabled=False` 或 `keyword_store=None` 时仅写 PG（`self._store.upsert`）
- **注入 `VectorStorePort`** 并内部转为 `PgVectorStore`（`# type: ignore[assignment]`），与 `upload_doc_use_case.py` 一致

### purge_document_chunks
- `keyword_store` 可选参数支持纯 PG 部署（无 ES 时跳过）
- ES 删除失败记录 warning 而非传播异常，因为 PG 端 CASCADE 已生效
