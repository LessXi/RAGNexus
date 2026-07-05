# Task 4.4-4.6: KB 运维路由 — GET/PATCH/DELETE

## 概述

创建 3 个 use case + 1 个 HTTP router，实现知识库的详情查询、部分更新和级联删除。

## 交付物

| 文件 | 说明 |
|------|------|
| `src/ragnexus/application/kb_detail_uc.py` | `KnowledgeBaseDetailUseCase` — 查 KB 详情，校验 tenant_id |
| `src/ragnexus/application/kb_update_uc.py` | `KnowledgeBaseUpdateUseCase` — 部分更新 name/description/settings |
| `src/ragnexus/application/kb_delete_uc.py` | `KnowledgeBaseDeleteUseCase` — 级联删除：关键词索引 → 文档 → KB |
| `src/ragnexus/adapters/http/kb_router.py` | `create_kb_router()` 工厂函数 — GET/PATCH/DELETE 三个端点 |

## 实现细节

### 1. `KnowledgeBaseDetailUseCase`
- 通过 `KnowledgeBasePort.get()` 查询 KB
- 校验 `kb.tenant_id == tenant_id`，不匹配抛 `NOT_FOUND`（防止横向越权）

### 2. `KnowledgeBaseUpdateUseCase`
- 先查 KB 并校验租户归属
- `settings` 参数非 None 但非 dict 时抛 `PARAM_ERROR`
- 委托 `KnowledgeBasePort.update()` 执行部分更新

### 3. `KnowledgeBaseDeleteUseCase`
- 校验租户归属
- 通过 `DocumentPort.has_processing()` 检查是否有索引中的文档，有则抛 `RESOURCE_CONFLICT`
- 若 `keyword_store` 存在，遍历文档逐条 `delete_by_document`（best-effort，异常静默吞掉）
- `DocumentPort.delete_by_kb()` → `KnowledgeBasePort.delete()` 级联清理

### 4. `kb_router.py` — `create_kb_router()`
- `GET /v1/knowledge-bases/{kb_id}` — 返回 KB 完整信息（id/name/description/settings/tenant_id/created_at）
- `PATCH /v1/knowledge-bases/{kb_id}` — 请求体可选 `name`/`description`/`settings`
- `DELETE /v1/knowledge-bases/{kb_id}` — 返回 `data: null`
- 工厂函数签名与其他 router 一致：注入 use case 实例 + `get_current_tenant`

## 验证

- [x] 4 个文件 AST 解析通过
- [x] 所有模块导入成功，无 ImportError
- [x] 依赖的 ErrorCode (`NOT_FOUND`, `PARAM_ERROR`, `RESOURCE_CONFLICT`) 已存在于 `core/errors.py`
- [x] 依赖的端口方法 (`KnowledgeBasePort.get/update/delete`, `DocumentPort.has_processing/get_by_kb/delete_by_kb`, `KeywordSearchPort.delete_by_document`) 已存在于 `domain/ports.py`
- [x] 路由工厂签名与 `composition.py` 中的 `app.include_router()` 调用模式兼容（待 composition.py 追加导入和注册）

## 待后续完成

- `composition.py` 中实例化 3 个 use case，创建 `kb_router` 并 `app.include_router()`
