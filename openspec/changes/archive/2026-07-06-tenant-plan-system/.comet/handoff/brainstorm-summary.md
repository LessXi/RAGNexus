# Brainstorm Summary

- Change: tenant-plan-system
- Date: 2026-07-06

## 确认的技术方案

核心架构：在 FastAPI 请求入口插入策略层，不侵入 RetrieveUseCase。

```
Auth(TenantContext.plan)
  → PlanResolver.resolve_plan(plan) → PlanContext
  → profile 校验 + retrieve_presets 展开
  → RateLimitService QPS check (Redis INCR)
  → QuotaService 日配额 check (Redis GET)
  → uc.execute(展开后的 options)  ← 现有链路不变
  → RateLimitService.record_success (Redis INCR)
  → 响应 + tenant_policy
```

5 个关键设计决策：
1. Profile 展开放 router 层（不侵入 UseCase）
2. TenantContext 加 plan 字段（get_by_hash JOIN 顺路带回）
3. plan_presets 硬编码（产品策略，不存 DB）
4. Redis 连接在 lifespan 中创建，注入 RateLimitService
5. API_RATE_LIMIT 从 20002 改为 20005

## 关键取舍与风险

| 取舍 | 理由 | 风险 | 缓解 |
|------|------|------|------|
| Profile 放 router | 请求预处理，不污染业务层 | custom 路径 plan ceiling 校验遗漏 | code review 确认 |
| plan_presets 硬编码 | 避免 DB 状态漂移 | 调整配额需发版 | 低频变更，可接受 |
| TenantContext 加 plan | 零额外查询 | _FALLBACK_TENANT.plan 需设为 pro | 静态常量，无风险 |
| Redis 复用 Celery 的 | 无需新配置 | key 冲突 | rag: 前缀隔离 |

## 测试策略

- 单元测试：plan_presets/retrieve_presets/plan_resolver 纯函数 + RateLimitService(mock Redis)
- 集成测试：QuotaService(test DB) + router handler 全链路
- E2E：文档3 的 12 个 curl 用例自动化

## Spec Patch

无 — 现有 delta spec 已覆盖全部 25 个 Scenario。
