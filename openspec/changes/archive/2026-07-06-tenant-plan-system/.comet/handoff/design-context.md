# Comet Design Handoff

- Change: tenant-plan-system
- Phase: design
- Mode: compact
- Context hash: f628057788f83ec2405f38f05b9e5565f70fdfb4752a1b4168b838e2799e70f7

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/tenant-plan-system/proposal.md

- Source: openspec/changes/tenant-plan-system/proposal.md
- Lines: 1-51
- SHA256: f0683bdac838f81851c8a53e023702381d473ef5bf63c61a50e3c5194cbc1fe7

```md
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
```

## openspec/changes/tenant-plan-system/design.md

- Source: openspec/changes/tenant-plan-system/design.md
- Lines: 1-123
- SHA256: 01b9683ded323f7e110380074e89a42dee443416896a5abf9cc8cecc9852d935

[TRUNCATED]

```md
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
```

Full source: openspec/changes/tenant-plan-system/design.md

## openspec/changes/tenant-plan-system/tasks.md

- Source: openspec/changes/tenant-plan-system/tasks.md
- Lines: 1-65
- SHA256: e2d3b004a343297e479a3c1d2fe142189aad58797305962a97986f7e6c904818

```md
## 1. 基础设施

- [ ] 1.1 创建 Alembic 迁移 0007，tenants 表加 plan 列，已有租户升级为 standard，tenant_demo 为 pro
- [ ] 1.2 创建 `src/ragnexus/tenant/plan_presets.py`：三档 PLAN_PRESETS 常量字典
- [ ] 1.3 创建 `src/ragnexus/tenant/retrieve_presets.py`：四档 RETRIEVE_PROFILE_PRESETS 展开规则
- [ ] 1.4 创建 `src/ragnexus/tenant/plan_resolver.py`：PlanContext dataclass + resolve_plan()
- [ ] 1.5 创建 `src/ragnexus/tenant/__init__.py`

## 2. 领域模型与鉴权扩展

- [ ] 2.1 `domain/models.py`：Tenant dataclass 加 plan 字段
- [ ] 2.2 `core/auth.py`：TenantContext 加 plan，_FALLBACK_TENANT plan="pro"
- [ ] 2.3 `adapters/tenant/pg.py`：get_by_hash() SQL 加 t.plan AS tenant_plan，PgTenantRepository.get() 加 plan
- [ ] 2.4 `core/errors.py`：新增 FEATURE_NOT_ALLOWED(20013)、QUOTA_EXCEEDED(20014)；API_RATE_LIMIT 从 20002 改为 20005

## 3. 限流与配额服务

- [ ] 3.1 创建 `src/ragnexus/services/__init__.py` 和 `rate_limit_service.py`：Redis QPS 限流 + 日配额计数
- [ ] 3.2 创建 `src/ragnexus/services/quota_service.py`：DB 配额检查（库数/文档数/并发 PROCESSING）
- [ ] 3.3 `composition.py`：创建 Redis 连接，注入 RateLimitService 和 QuotaService

## 4. 检索链路改造

- [ ] 4.1 `adapters/http/retrieve_router.py`：_RetrieveRequest 加 profile 可选字段（默认 balanced）
- [ ] 4.2 retrieve router handler：插入 plan 解析 → profile 校验/展开 → QPS 限流 → 日配额检查 → 调用 uc.execute()
- [ ] 4.3 retrieve router handler：检索成功后日计数 +1，响应加 metadata.tenant_policy

## 5. 配额入口接入

- [ ] 5.1 `adapters/http/create_kb_router.py`：建库前检查库数配额
- [ ] 5.2 `adapters/http/upload_doc_router.py`：上传前检查单库文档数 + 并发 PROCESSING 配额
- [ ] 5.3 `adapters/http/document_router.py`：reindex 前检查并发 PROCESSING 配额

## 6. /auth/me 扩展

- [ ] 6.1 `adapters/http/auth_router.py`：注入 tenant_repo + rate_limiter，扩展返回 plan/features/limits/usage
- [ ] 6.2 `composition.py`：更新 create_auth_router 调用，传入新依赖

## 7. 运维脚本

- [ ] 7.1 创建 `scripts/update_tenant_plan.py`：--tenant-id --plan，校验 plan 合法性和 tenant 存在性

## 8. 前端类型与 API 适配

- [ ] 8.1 `admin/src/types/api.ts`：AuthMeData 扩展 plan/features/limits/usage；RetrieveRequest 加 profile
- [ ] 8.2 `admin/src/services/authService.ts` 和 `admin/src/services/ragService.ts`：类型适配，retrieve 带 profile
- [ ] 8.3 统一 fetchAuthMe：删除 `admin/src/services/api.ts` 中的旧版本，全部导向 authService.ts

## 9. 前端调试台

- [ ] 9.1 `admin/src/pages/RetrievePage.tsx`：四档 profile 选择器（Tab/Radio），按 plan 置灰 + tooltip
- [ ] 9.2 `admin/src/pages/RetrievePage.tsx`：custom 联动（展开高级参数，按 plan 置灰各项）
- [ ] 9.3 `admin/src/pages/RetrievePage.tsx`：speed/balanced/quality 时折叠高级参数区
- [ ] 9.4 `admin/src/pages/KnowledgeFileTreePage.tsx`：顶栏加 plan badge（免费灰/标准蓝/专业紫）
- [ ] 9.5 `admin/src/pages/KnowledgeUploadPage.tsx`：捕获 20014 错误并展示 msg

## 10. 文档与测试

- [ ] 10.1 创建 `docs/tenant-onboarding.md` 接入文档（含 plan 对照表、profile 说明、错误码表、curl 示例）
- [ ] 10.2 README.md 加链接指向 tenant-onboarding.md
- [ ] 10.3 验证：alembic upgrade 成功，旧 tenant 为 standard
- [ ] 10.4 验证：free+speed 成功 / free+balanced 20013 / pro+quality 成功 / standard+custom+rerank 20013
- [ ] 10.5 验证：free 建第二个库 20014 / QPS 超限 20005 / 日配额超限
- [ ] 10.6 验证：/auth/me 返回完整字段 / 跨租户隔离
- [ ] 10.7 验证：前端 pro 四档全可选 / standard quality 置灰 / free 仅 speed / badge + 配额错误
```

## openspec/changes/tenant-plan-system/specs/auth-me-extension/spec.md

- Source: openspec/changes/tenant-plan-system/specs/auth-me-extension/spec.md
- Lines: 1-29
- SHA256: 864729400f7995449aaff81bd78e647b6923695f1337c05909070833406ce8a9

```md
## ADDED Requirements

### Requirement: /auth/me 返回 plan 字段

`GET /v1/auth/me` SHALL 在响应 data 中返回 `plan` 字段，值为 free / standard / pro。

#### Scenario: standard 租户查询身份
- **WHEN** standard 租户的 API Key 请求 /auth/me
- **THEN** 响应 data.plan SHALL 为 "standard"

### Requirement: /auth/me 返回 features 字段

`GET /v1/auth/me` SHALL 在响应 data 中返回 `features` 对象，包含 allowed_profiles、hybrid_allowed、rerank_allowed、query_rewrite_allowed。

#### Scenario: standard 租户 features
- **WHEN** standard 租户请求 /auth/me
- **THEN** data.features.allowed_profiles SHALL 为 ["speed", "balanced", "custom"]，data.features.rerank_allowed SHALL 为 false

### Requirement: /auth/me 返回 limits 字段

`GET /v1/auth/me` SHALL 在响应 data 中返回 `limits` 对象，包含 retrieve_qps、retrieve_daily、max_kb、max_documents_per_kb、max_processing_documents。

### Requirement: /auth/me 返回 usage 字段

`GET /v1/auth/me` SHALL 在响应 data 中返回 `usage` 对象，包含 kb_count（从 DB 实时查询）和 retrieve_daily_count（从 Redis 实时查询）。

#### Scenario: usage 实时反映当前用量
- **WHEN** standard 租户请求 /auth/me
- **THEN** data.usage.kb_count SHALL 等于该租户下知识库的实际数量；data.usage.retrieve_daily_count SHALL 等于 Redis 中日检索计数器的当前值
```

## openspec/changes/tenant-plan-system/specs/rate-limiting-and-quota/spec.md

- Source: openspec/changes/tenant-plan-system/specs/rate-limiting-and-quota/spec.md
- Lines: 1-53
- SHA256: 67f4e09b281ddaa258655352acf9ddee2e8f7fe71e2672bcbf3d04dffbcce4b6

```md
## ADDED Requirements

### Requirement: QPS 限流

系统 SHALL 通过 Redis 对检索请求执行基于租户的 QPS 限流。Redis key 格式为 `rag:ratelimit:retrieve:{tenant_id}:{unix_second}`，TTL 2 秒。

#### Scenario: QPS 未超限正常放行
- **WHEN** free 租户（QPS=3）在 1 秒内第 1-3 次检索
- **THEN** 请求 SHALL 正常放行

#### Scenario: QPS 超限拒绝
- **WHEN** free 租户（QPS=3）在 1 秒内第 4 次检索
- **THEN** 系统 SHALL 返回 code=20005, message 含 "检索 QPS 超限"

### Requirement: 日检索量配额

系统 SHALL 通过 Redis 跟踪每个租户的日检索量。Redis key 格式为 `rag:quota:retrieve:daily:{tenant_id}:{YYYYMMDD}`，TTL 25 小时。仅在检索成功后 +1，失败/被拒绝的不计数。

#### Scenario: 日配额未超继续检索
- **WHEN** free 租户（日上限 500）当日检索 500 次
- **THEN** 第 501 次请求 SHALL 返回 code=20014, message 含 "日检索量已达上限"

#### Scenario: 检索失败不计数
- **WHEN** 检索因 profile 校验返回 20013 或因 QPS 返回 20005
- **THEN** 日配额计数器 SHALL NOT 增长

### Requirement: 建库配额

系统 SHALL 在建库前检查租户下的知识库数不超过 plan.limits.max_kb。

#### Scenario: free 建第二个库被拒绝
- **WHEN** free 租户已有 1 个知识库，尝试再建一个
- **THEN** 系统 SHALL 返回 code=20014, message 含 "免费档仅支持 1 个知识库"

### Requirement: 上传配额

系统 SHALL 在上传文档前检查 (1) 单库文档数不超过 max_documents_per_kb，(2) 租户下 PROCESSING 状态的文档数不超过 max_processing_documents。

#### Scenario: 单库文档数超限
- **WHEN** free 租户在已有 30 个文档的库中再上传
- **THEN** 系统 SHALL 返回 code=20014

#### Scenario: 并发 PROCESSING 超限
- **WHEN** free 租户已有 1 个 PROCESSING 文档，再上传第二个
- **THEN** 系统 SHALL 返回 code=20014, message 含 "并发索引文档数已达上限"

### Requirement: Reindex 配额

系统 SHALL 在 reindex 前检查租户下 PROCESSING 状态的文档数不超过 max_processing_documents。

#### Scenario: reindex 超并发限制
- **WHEN** free 租户已有 1 个 PROCESSING 文档，对另一文档发起 reindex
- **THEN** 系统 SHALL 返回 code=20014
```

## openspec/changes/tenant-plan-system/specs/retrieve-api/spec.md

- Source: openspec/changes/tenant-plan-system/specs/retrieve-api/spec.md
- Lines: 1-80
- SHA256: 9ea45a0e8bbbc56b34b559c53c0fdb9966ced57d280807963777f6a0d6c93644

```md
## MODIFIED Requirements

### Requirement: 请求新增 profile 参数

检索请求体 SHALL 新增可选字段 `profile`，取值 speed / balanced / quality / custom。未传时默认 `balanced`。

```json
{
  "profile": "balanced",
  "query": "...",
  "kb_ids": [...]
}
```

#### Scenario: 传 profile=speed
- **WHEN** 请求包含 `profile: "speed"`
- **THEN** 系统 SHALL 按 speed 预设展开检索参数（mode=vector, top_k=3, 关闭 rerank 和 rewrite）

#### Scenario: 不传 profile 默认 balanced
- **WHEN** 请求未包含 `profile` 字段
- **THEN** 系统 SHALL 按 balanced 预设展开（mode=hybrid, top_k=5, 关闭 rerank 和 rewrite）
- **AND** 行为 SHALL 与改前一致（向后兼容）

#### Scenario: profile 不被 plan 允许
- **WHEN** free 租户传 `profile: "balanced"`
- **THEN** 系统 SHALL 返回 code=20013, 不执行检索

### Requirement: 响应 meta 新增 tenant_policy

响应 `meta` SHALL 新增可选字段 `tenant_policy`，描述本次检索生效的策略参数：

```json
{
  "meta": {
    "tenant_policy": {
      "plan": "pro",
      "retrieve_profile": "quality",
      "effective_mode": "hybrid",
      "effective_rerank": true,
      "effective_query_rewrite": true
    }
  }
}
```

#### Scenario: quality profile 返回完整 tenant_policy
- **WHEN** pro 租户传 profile=quality
- **THEN** meta.tenant_policy.plan SHALL 为 "pro"
- **AND** meta.tenant_policy.retrieve_profile SHALL 为 "quality"
- **AND** meta.tenant_policy.effective_rerank SHALL 为 true
- **AND** meta.tenant_policy.effective_query_rewrite SHALL 为 true

#### Scenario: speed profile 不启用高级功能
- **WHEN** 任意租户传 profile=speed
- **THEN** meta.tenant_policy.effective_rerank SHALL 为 false
- **AND** meta.tenant_policy.effective_query_rewrite SHALL 为 false

### Requirement: 错误码 API_RATE_LIMIT 变更为 20005

`ErrorCode.API_RATE_LIMIT` 的业务错误码 SHALL 从 20002 改为 20005。HTTP 状态码 429 保持不变。

#### Scenario: QPS 超限返回 20005
- **WHEN** 检索 QPS 超限
- **THEN** 系统 SHALL 返回 `"code": 20005`, HTTP 429

### Requirement: 新增错误码 FEATURE_NOT_ALLOWED (20013)

系统 SHALL 支持错误码 `FEATURE_NOT_ALLOWED` (20013, HTTP 403)，在 plan 不允许请求的 profile 或 options 时返回。

#### Scenario: profile 超 plan 返回 20013
- **WHEN** free 租户传 profile=balanced
- **THEN** 系统 SHALL 返回 `"code": 20013, message: "当前套餐 free 不支持检索预设 balanced"`, HTTP 403

### Requirement: 新增错误码 QUOTA_EXCEEDED (20014)

系统 SHALL 支持错误码 `QUOTA_EXCEEDED` (20014, HTTP 429)，在租户超出配额上限时返回。

#### Scenario: 建库超配额返回 20014
- **WHEN** free 租户尝试创建第二个知识库
- **THEN** 系统 SHALL 返回 `"code": 20014, message: "免费档仅支持 1 个知识库"`, HTTP 429
```

## openspec/changes/tenant-plan-system/specs/retrieve-profiles/spec.md

- Source: openspec/changes/tenant-plan-system/specs/retrieve-profiles/spec.md
- Lines: 1-62
- SHA256: 1654120b1b99590f8e5aca68cd6d24b60e7cc27d578eda0fef786abef5b6d24e

```md
## ADDED Requirements

### Requirement: 四档检索预设定义

系统 SHALL 支持四档检索预设（speed / balanced / quality / custom），定义在 `retrieve_presets.py` 常量中。

- **speed**: mode=vector, top_k=3, 关 rerank 和 rewrite
- **balanced**: mode=hybrid, top_k=5, 关 rerank 和 rewrite（默认）
- **quality**: mode=hybrid, top_k=8, 开 rerank(take=5) 和 rewrite
- **custom**: 不展开默认值，使用请求中显式传入的 options

#### Scenario: 未传 profile 默认 balanced
- **WHEN** 检索请求未包含 `profile` 字段
- **THEN** 系统 SHALL 按 balanced 预设展开，mode=hybrid, top_k=5, rerank 和 rewrite 关闭

#### Scenario: speed 预设展开
- **WHEN** profile=speed
- **THEN** 系统 SHALL 展开为 mode=vector, top_k=3, rerank_enabled=false, query_options={"enabled":false}

#### Scenario: quality 预设展开
- **WHEN** profile=quality
- **THEN** 系统 SHALL 展开为 mode=hybrid, top_k=8, rerank_enabled=true, rerank_top_n=5, query_options={"enabled":true,"strategy":"rewrite"}

### Requirement: Profile 与 Plan 的校验

系统 SHALL 按 plan 校验 profile：profile 不在 plan.features.allowed_profiles 列表时 MUST 返回 20013。

- free: ["speed"]
- standard: ["speed", "balanced", "custom"]
- pro: ["speed", "balanced", "quality", "custom"]

#### Scenario: free 请求 balanced 被拒绝
- **WHEN** free 租户传 profile=balanced
- **THEN** 系统 SHALL 返回 code=20013, message 含 "当前套餐 free 不支持检索预设 balanced"

#### Scenario: standard 请求 quality 被拒绝
- **WHEN** standard 租户传 profile=quality
- **THEN** 系统 SHALL 返回 code=20013

#### Scenario: pro 请求 quality 成功
- **WHEN** pro 租户传 profile=quality
- **THEN** 系统 SHALL 成功执行，metadata.tenant_policy.retrieve_profile 为 quality, effective_rerank 为 true

### Requirement: Custom profile 受 plan 约束

当 profile=custom 时，系统 SHALL 使用请求中显式传入的 options，但仍 MUST 校验各选项不超过 plan.features 上限。

#### Scenario: standard + custom + rerank 被拒绝
- **WHEN** standard 租户传 profile=custom 且 rerank_options.enabled=true
- **THEN** 系统 SHALL 返回 code=20013，因为 standard 不允许 rerank

#### Scenario: free + custom + hybrid 被拒绝
- **WHEN** free 租户传 profile=custom 且 mode=hybrid
- **THEN** 系统 SHALL 返回 code=20013，因为 free 不允许 hybrid

### Requirement: Plan ceiling 优先于 .env 全局开关

Profile 展开后的参数 MUST 覆盖（而非叠加）uc.execute() 的参数。即使 `.env` 中 `RERANK_ENABLED=true`，free 租户的 balanced profile 展开后 rerank_enabled=false MUST 生效。

#### Scenario: .env RERANK_ENABLED=true 但 free balanced 不 rerank
- **WHEN** `.env` 设 `RERANK_ENABLED=true` 且 free 租户传 profile=balanced
- **THEN** 传给 `uc.execute()` 的 rerank_enabled SHALL 为 false
```

## openspec/changes/tenant-plan-system/specs/tenant-plans/spec.md

- Source: openspec/changes/tenant-plan-system/specs/tenant-plans/spec.md
- Lines: 1-41
- SHA256: cbd22d2632bd900e063a17c00004b7f26dcf1eef7335ffb2b7851f6a30a56f95

```md
## ADDED Requirements

### Requirement: 三档租户套餐定义

系统 SHALL 支持三档租户套餐（free、standard、pro），每档包含功能开关和配额上限，硬编码在 `plan_presets.py` 常量中。

#### Scenario: free 套餐限制
- **WHEN** 租户 plan 为 free
- **THEN** 该租户 SHALL 仅能使用 speed profile，最多 1 个知识库，单库 30 个文档，QPS 上限 3，日检索上限 500，且不能使用 hybrid/rerank/rewrite

#### Scenario: standard 套餐限制
- **WHEN** 租户 plan 为 standard
- **THEN** 该租户 SHALL 能使用 speed/balanced/custom profile，最多 5 个知识库，单库 200 个文档，QPS 上限 10，日检索上限 5000，可使用 hybrid 但不能用 rerank/rewrite

#### Scenario: pro 套餐全功能
- **WHEN** 租户 plan 为 pro
- **THEN** 该租户 SHALL 能使用全部四档 profile，最多 50 个知识库，单库 5000 个文档，QPS 上限 50，日检索上限 100000，可使用全部功能

### Requirement: 租户 plan 持久化与迁移

`tenants` 表 SHALL 新增 `plan VARCHAR(32) NOT NULL DEFAULT 'free'` 列。Alembic 迁移 SHALL 将已有租户设为 `standard`，`tenant_demo` 设为 `pro`。

#### Scenario: 新租户默认 free
- **WHEN** 通过 `create_tenant.py` 创建新租户且未指定 plan
- **THEN** 该租户的 plan SHALL 为 free

#### Scenario: 通过脚本修改 plan
- **WHEN** 执行 `update_tenant_plan.py --tenant-id <id> --plan <plan>`
- **THEN** 若 plan 为 free/standard/pro 之一，租户 plan SHALL 更新成功；若 plan 非法，脚本 SHALL 报错退出

### Requirement: 鉴权上下文携带 plan

`TenantContext` SHALL 包含 `plan` 字段。`get_by_hash()` SQL 查询 SHALL 从 JOIN 的 tenants 表顺路带回 plan 列。

#### Scenario: 鉴权成功携带 plan
- **WHEN** API Key 鉴权通过
- **THEN** `TenantContext.plan` SHALL 为对应租户的 plan 值

#### Scenario: 鉴权禁用时默认 plan
- **WHEN** `AUTH_ENABLED=false`
- **THEN** `_FALLBACK_TENANT.plan` SHALL 为 `pro`
```

