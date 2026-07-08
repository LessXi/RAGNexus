## Why

当前所有租户共用同一套检索默认值，谁都能无限建库、随意开 rerank——无法做差异化服务和资源管控。需要将 Tenant 从"仅做鉴权隔离的标签"升级为"承载资源配额和功能开关的策略实体"，让 free/standard/pro 三档套餐各司其职。

## What Changes

### 新增
- 系统 SHALL 支持三档租户套餐: free、standard、pro，硬编码在 `plan_presets.py` 中
- 检索端点 SHALL 接受可选 `profile` 参数（speed / balanced / quality / custom），未传默认 `balanced`
- 系统 SHALL 按 plan 校验 profile：plan 不允许的 profile MUST 返回 20013 FEATURE_NOT_ALLOWED
- 系统 SHALL 对建库、上传、reindex 三个入口强制执行配额检查（库数/文档数/并发索引）
- 系统 SHALL 通过 Redis 强制执行 QPS 和日检索量限流
- `/auth/me` 端点 SHALL 返回 plan、features、limits、usage 字段
- 前端调试台 SHALL 展示 plan badge、profile 选择器（按 plan 置灰不可用项）、配额错误提示

### 修改
- `TenantContext` SHALL 新增 `plan` 字段（从 `get_by_hash()` JOIN 顺路带回）
- `_RetrieveRequest` SHALL 新增可选 `profile` 字段
- retrieve router MUST 在调用 `RetrieveUseCase` 前完成 plan 校验 + profile 展开 + 限流检查
- `create_kb_router` / `upload_doc_router` / `document_router` SHALL 在执行业务逻辑前检查配额
- 错误码 `FEATURE_NOT_ALLOWED`(20013) 和 `QUOTA_EXCEEDED`(20014) SHALL 新增；`API_RATE_LIMIT` SHALL 从 20002 改为 20005
- plan ceiling MUST 优先于 `.env` 全局开关：profile 展开后的参数直接覆盖 uc.execute() 参数

### 不变
- `RetrieveUseCase.execute()` 签名不变（向后兼容：不传 profile 时 balanced 展开 = 当前默认行为 hybrid）
- chunk / documents / retrieve_logs 表结构不变
- `settings.synonyms` 词表各 plan 都能用
- Celery Worker 索引管道不变

## Capabilities

### New Capabilities
- `tenant-plans`: 三档租户套餐定义（free/standard/pro），功能开关与配额上限，租户生命周期管理（迁移脚本、`update_tenant_plan.py`）
- `retrieve-profiles`: 四档检索预设（speed/balanced/quality/custom），profile 展开规则，plan 与 profile 的校验关系
- `rate-limiting-and-quota`: Redis QPS 限流 + 日检索量配额 + DB 资源配额检查（库数/文档数/并发索引）
- `auth-me-extension`: `/auth/me` 扩展返回 plan、features、limits、usage 字段

### Modified Capabilities
- `retrieve-api`: **BREAKING** 所有检索请求新增 `profile` 参数行为——未传默认 `balanced`，plan 不匹配的 profile 返回 20013；响应新增 `metadata.tenant_policy` 字段；`API_RATE_LIMIT` 错误码从 20002 改为 20005

## Impact

| 维度 | 影响 |
|------|------|
| **DB** | `tenants` 表加 `plan VARCHAR(32) NOT NULL DEFAULT 'free'`（migration 0007） |
| **Redis** | 新 key 前缀 `rag:ratelimit:` / `rag:quota:`，复用 CELERY_BROKER_URL |
| **API** | `/v1/rag:retrieve` 请求加 `profile`，响应加 `tenant_policy`；`/v1/auth/me` 响应扩展 |
| **后端** | 6 个新建模块 + 7 个扩展现有文件，约 400 行新代码 |
| **前端** | 7 个文件改动，profile 选择器 + plan badge + 错误处理 |
| **脚本** | 新增 `scripts/update_tenant_plan.py` |
| **文档** | 新增 `docs/tenant-onboarding.md` 接入文档 |
