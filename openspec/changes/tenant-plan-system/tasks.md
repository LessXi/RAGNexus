## 1. 基础设施

- [x] 1.1 创建 Alembic 迁移 0007，tenants 表加 plan 列，已有租户升级为 standard，tenant_demo 为 pro
- [x] 1.2 创建 `src/ragnexus/tenant/plan_presets.py`：三档 PLAN_PRESETS 常量字典
- [x] 1.3 创建 `src/ragnexus/tenant/retrieve_presets.py`：四档 RETRIEVE_PROFILE_PRESETS 展开规则
- [x] 1.4 创建 `src/ragnexus/tenant/plan_resolver.py`：PlanContext dataclass + resolve_plan()
- [x] 1.5 创建 `src/ragnexus/tenant/__init__.py`

## 2. 领域模型与鉴权扩展

- [x] 2.1 `domain/models.py`：Tenant dataclass 加 plan 字段
- [x] 2.2 `core/auth.py`：TenantContext 加 plan，_FALLBACK_TENANT plan="pro"
- [x] 2.3 `adapters/tenant/pg.py`：get_by_hash() SQL 加 t.plan AS tenant_plan，PgTenantRepository.get() 加 plan
- [x] 2.4 `core/errors.py`：新增 FEATURE_NOT_ALLOWED(20013)、QUOTA_EXCEEDED(20014)；API_RATE_LIMIT 从 20002 改为 20005

## 3. 限流与配额服务

- [x] 3.1 创建 `src/ragnexus/services/__init__.py` 和 `rate_limit_service.py`：Redis QPS 限流 + 日配额计数
- [x] 3.2 创建 `src/ragnexus/services/quota_service.py`：DB 配额检查（库数/文档数/并发 PROCESSING）
- [x] 3.3 `composition.py`：创建 Redis 连接，注入 RateLimitService 和 QuotaService

## 4. 检索链路改造

- [x] 4.1 `adapters/http/retrieve_router.py`：_RetrieveRequest 加 profile 可选字段（默认 balanced）
- [x] 4.2 retrieve router handler：插入 plan 解析 → profile 校验/展开 → QPS 限流 → 日配额检查 → 调用 uc.execute()
- [x] 4.3 retrieve router handler：检索成功后日计数 +1，响应加 metadata.tenant_policy

## 5. 配额入口接入

- [x] 5.1 `adapters/http/create_kb_router.py`：建库前检查库数配额
- [x] 5.2 `adapters/http/upload_doc_router.py`：上传前检查单库文档数 + 并发 PROCESSING 配额
- [x] 5.3 `adapters/http/document_router.py`：reindex 前检查并发 PROCESSING 配额

## 6. /auth/me 扩展

- [x] 6.1 `adapters/http/auth_router.py`：注入 tenant_repo + rate_limiter，扩展返回 plan/features/limits/usage
- [x] 6.2 `composition.py`：更新 create_auth_router 调用，传入新依赖

## 7. 运维脚本

- [x] 7.1 创建 `scripts/update_tenant_plan.py`：--tenant-id --plan，校验 plan 合法性和 tenant 存在性

## 8. 前端类型与 API 适配

- [x] 8.1 `admin/src/types/api.ts`：AuthMeData 扩展 plan/features/limits/usage；RetrieveRequest 加 profile
- [x] 8.2 `admin/src/services/authService.ts` 和 `admin/src/services/ragService.ts`：类型适配，retrieve 带 profile
- [x] 8.3 统一 fetchAuthMe：删除 `admin/src/services/api.ts` 中的旧版本，全部导向 authService.ts

## 9. 前端调试台

- [x] 9.1 `admin/src/pages/RetrievePage.tsx`：四档 profile 选择器（Tab/Radio），按 plan 置灰 + tooltip
- [x] 9.2 `admin/src/pages/RetrievePage.tsx`：custom 联动（展开高级参数，按 plan 置灰各项）
- [x] 9.3 `admin/src/pages/RetrievePage.tsx`：speed/balanced/quality 时折叠高级参数区
- [x] 9.4 `admin/src/pages/KnowledgeFileTreePage.tsx`：顶栏加 plan badge（免费灰/标准蓝/专业紫）
- [x] 9.5 `admin/src/pages/KnowledgeUploadPage.tsx`：捕获 20014 错误并展示 msg

## 10. 文档与测试

- [x] 10.1 创建 `docs/tenant-onboarding.md` 接入文档（含 plan 对照表、profile 说明、错误码表、curl 示例）
- [x] 10.2 README.md 加链接指向 tenant-onboarding.md
- [x] 10.3 验证：alembic upgrade 成功，旧 tenant 为 standard
- [x] 10.4 验证：free+speed 成功 / free+balanced 20013 / pro+quality 成功 / standard+custom+rerank 20013
- [x] 10.5 验证：free 建第二个库 20014 / QPS 超限 20005 / 日配额超限
- [x] 10.6 验证：/auth/me 返回完整字段 / 跨租户隔离
- [x] 10.7 验证：前端 pro 四档全可选 / standard quality 置灰 / free 仅 speed / badge + 配额错误
