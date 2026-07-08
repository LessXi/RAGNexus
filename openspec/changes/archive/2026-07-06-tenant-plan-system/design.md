## Context

当前 RAGNexus 的 Tenant 仅做鉴权隔离（`TenantContext` 含 tenant_id/name/key 信息），所有租户共享同一套检索默认值。`RetrieveUseCase` 行为由 `.env` 全局开关 + 请求参数决定，无差异化能力。

参照分析文档 `docs/analysis/tenant-plan-analysis.md`（12 章，15212 字节）的架构对齐结果，本设计聚焦于以最小侵入方式插入一层"策略层"。

## Goals / Non-Goals

**Goals:**
- 在检索请求入口插入 plan 校验 + profile 展开 + 限流检查
- 在三个写入口（建库/上传/reindex）加配额检查
- `/auth/me` 扩展返回 plan 元数据
- 前端调试台展示套餐状态和 profile 选择
- plan 校验优先于 `.env` 全局开关
- 不传 profile 时向后兼容（balanced ≈ 当前默认 hybrid 行为）

**Non-Goals:**
- 不引入新的 HTTP 路由或 API 版本号
- 不改 `RetrieveUseCase.execute()` 签名
- 不新增数据库表（仅 tenants 加一列）
- 不做在线改 plan 的 UI
- 不做计费/支付

## Decisions

### D1: Profile 展开放 Router 层，不侵入 UseCase

**选择**：在 `retrieve_router.py` 的 handler 中完成 plan 解析 → profile 校验/展开 → 限流检查，然后将展开后的参数传给 `uc.execute()` 的现有参数。

**理由**：
- Profile 展开是"请求预处理"，不是业务编排
- `retrieve_presets.py` 是纯函数字典查找，无需依赖注入
- `RetrieveUseCase.execute()` 签名不变，向后兼容
- 只有限流/配额检查需要新服务（Redis/DB），通过 DI 注入 router

**替代方案**：在 `RetrieveUseCase` 内部做 profile 展开 → 被拒绝，因为 UseCase 不应关心 HTTP 层概念。

### D2: TenantContext 加 plan 字段

**选择**：`TenantContext` 新增 `plan: str`，从 `get_by_hash()` SQL 的 JOIN 顺路带回。

**理由**：`get_by_hash()` 已 `JOIN tenants`，`t.plan` 零额外查询。后续所有路由都能通过 `current_tenant.plan` 拿到套餐。

**替代方案**：每个路由单独查 `tenant_repo.get()` → 被拒绝，多一次 DB 查询。

### D3: plan_presets 硬编码，不存 DB

**选择**：三档套餐配置写死在 `plan_presets.py` 常量字典，不支持 per-tenant 覆盖。

**理由**：套餐是产品策略，不是租户配置。需要调整时改代码发版，避免 DB 状态漂移和迁移复杂度。

### D4: Redis 限流复用 Celery 的 Redis

**选择**：`RateLimitService` 使用 `CELERY_BROKER_URL` 对应的 Redis 连接，key 加 `rag:` 前缀。

**理由**：无需新增 Redis 实例或配置项。key 前缀隔离避免与 Celery key 冲突。

### D5: `API_RATE_LIMIT` 错误码统一为 20005

**选择**：将现有 `ErrorCode.API_RATE_LIMIT` 从 20002 改为 20005。

**理由**：需求文档的 curl 测试用例使用 20005。统一后避免混淆。需要 grep 所有引用并更新。

## Architecture

```
请求 → Auth (TenantContext.plan)
     → Router: PlanResolver.resolve(plan) → PlanContext
     → Router: profile 校验 + 展开 → options
     → Router: RateLimitService QPS check
     → Router: QuotaService 日配额 check
     → UseCase: execute(query, kb_ids, tenant_id, mode=options.mode, ...)
     → Router: RateLimitService.record_success
     → 响应 + tenant_policy
```

### 新增模块

```
src/ragnexus/tenant/
  plan_presets.py       # PLAN_PRESETS 三档常量
  retrieve_presets.py   # RETRIEVE_PROFILE_PRESETS 四档展开
  plan_resolver.py      # PlanContext + resolve_plan()

src/ragnexus/services/
  rate_limit_service.py # Redis QPS + 日配额
  quota_service.py      # DB 配额检查
```

### 改动文件

| 文件 | 改动 |
|------|------|
| `core/auth.py` | TenantContext + plan, _FALLBACK_TENANT plan="pro" |
| `adapters/tenant/pg.py` | get_by_hash SQL + t.plan |
| `adapters/http/retrieve_router.py` | profile 参数 + plan 校验 + profile 展开 + 限流 |
| `adapters/http/auth_router.py` | /auth/me 扩展 plan/features/limits/usage |
| `adapters/http/create_kb_router.py` | 建库配额检查 |
| `adapters/http/upload_doc_router.py` | 上传配额检查 |
| `adapters/http/document_router.py` | reindex 配额检查 |
| `core/errors.py` | 20013/20014 + 修正 20005 |
| `domain/models.py` | Tenant + plan 字段 |
| `composition.py` | DI 注入新服务 + router 适配 |

### 数据库迁移

```sql
-- 0007_tenant_plan
ALTER TABLE tenants ADD COLUMN plan VARCHAR(32) NOT NULL DEFAULT 'free';
UPDATE tenants SET plan = 'standard' WHERE id NOT IN ('tenant_demo');
UPDATE tenants SET plan = 'pro' WHERE id = 'tenant_demo';
```

## Risks / Trade-offs

| 风险 | 等级 | 缓解 |
|------|------|------|
| plan ceiling vs .env 优先级 | 高 | Router 层覆盖参数；code review 确认 custom 路径 |
| API_RATE_LIMIT code 变更 | 中 | grep 全部引用点，更新测试用例 |
| asyncpg JSONB 返回 str | 低 | 本设计不涉及新 JSONB 读写 |
| Docker 无热重载 | 低 | 遵循 AGENTS.md: 改代码 → build → up |
| 日配额 TTL 25h 跨零点 | 低 | 标准 Redis TTL 模式，已验证可行 |
| 前端双 fetchAuthMe | 低 | 统一用 authService.ts 版本 |
