# Task 4.1-4.3 文档运维路由 — 实施报告

## 状态：✅ 完成

## 创建的文件

| # | 文件 | 用途 |
|---|------|------|
| 1 | `src/ragnexus/application/document_query_uc.py` | `DocumentQueryUseCase` — 查询单个文档详情 |
| 2 | `src/ragnexus/application/document_delete_uc.py` | `DocumentDeleteUseCase` — 删除文档 |
| 3 | `src/ragnexus/application/document_reindex_uc.py` | `DocumentReindexUseCase` — 重新索引 FAILED 文档 |
| 4 | `src/ragnexus/adapters/http/document_router.py` | `create_document_router()` — 暴露 GET/DELETE/POST reindex 端点 |

## 验证结果

- **导入检查**：4 个文件全部可导入，无 `ImportError`
- **一致性**：所有 use case 遵循 `async def execute(doc_id, tenant_id)` 签名，所有路由遵循 `create_*_router(uc, get_current_tenant) -> APIRouter` 工厂模式
- **租户隔离**：3 个 use case 均通过 `kb.tenant_id != tenant_id → NOT_FOUND` 防止跨租户访问
- **状态约束**：PROCESSING 文档拒绝删除（`RESOURCE_CONFLICT`），reindex 仅允许 FAILED 状态

## 端点清单

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/v1/documents/{doc_id}` | 查询文档详情 |
| DELETE | `/v1/documents/{doc_id}` | 删除文档（含向量/关键词索引清理） |
| POST | `/v1/documents/{doc_id}/reindex` | 重新索引 FAILED 文档 |

## Commit

```
feat(api): 文档运维路由 — GET/DELETE/reindex
```
