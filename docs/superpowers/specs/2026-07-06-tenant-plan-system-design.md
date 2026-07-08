---
comet_change: tenant-plan-system
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-06-tenant-plan-system
status: final
---

# RAGNexus 租户套餐系统 — 技术设计

> 基于 `openspec/changes/tenant-plan-system/` 的 proposal + design + specs

## 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│  请求 POST /v1/rag:retrieve { query, kb_ids, profile? }         │
└────────────┬────────────────────────────────────────────────────┘
             │
    ┌────────▼────────┐
    │ 1. 鉴权          │  get_current_tenant() → TenantContext(plan)
    │                  │  get_by_hash SQL 已 JOIN tenants.t.plan
    └────────┬────────┘
             │
    ┌────────▼────────┐  ┌─────────────────────────────────────────┐
    │ 2. PlanResolver  │  │ src/ragnexus/tenant/plan_resolver.py   │
    │   resolve_plan() │  │ 纯函数: plan → PlanContext               │
    └────────┬────────┘  │ PlanContext(features, limits)            │
             │            └─────────────────────────────────────────┘
    ┌────────▼────────┐  ┌─────────────────────────────────────────┐
    │ 3. Profile 校验  │  │ src/ragnexus/tenant/retrieve_presets.py │
    │    + 展开        │  │ profile ∉ allowed → 20013               │
    └────────┬────────┘  │ 非 custom → presets[profile] → options   │
             │            │ custom → 请求 options + plan ceiling    │
    ┌────────▼────────┐  ┌─────────────────────────────────────────┐
    │ 4. QPS 限流      │  │ src/ragnexus/services/rate_limit_svc.py │
    │                  │  │ Redis INCR rag:ratelimit:retr:{tid}:{s} │
    └────────┬────────┘  │ 超限 → 20005                            │
             │            └─────────────────────────────────────────┘
    ┌────────▼────────┐  ┌─────────────────────────────────────────┐
    │ 5. 日配额        │  │ Redis GET rag:quota:retr:daily:{tid}:d  │
    │                  │  │ ≥ limits.retrieve_daily → 20014         │
    └────────┬────────┘  └─────────────────────────────────────────┘
             │
    ┌────────▼────────┐
    │ 6. 检索管道      │  uc.execute(query, kb_ids, tenant_id,
    │  (现有链不变)    │    mode=options.mode,
    │                  │    rerank_enabled=options.rerank_enabled,
    │                  │    query_options=options.query_options)
    └────────┬────────┘
             │
    ┌────────▼────────┐  ┌─────────────────────────────────────────┐
    │ 7. 日计数 +1     │  │ Redis INCR rag:quota:retr:daily:{tid}:d │
    │    + tenant_policy│  │ 响应 meta.tenant_policy                 │
    └─────────────────┘  └─────────────────────────────────────────┘
```

### 配额入口

```
POST /v1/knowledge-bases:create  → QuotaService.check_kb_count(tenant_id, plan)
POST /v1/documents:upload        → QuotaService.check_doc_upload(kb_id, tenant_id, plan)
POST /v1/documents/{id}/reindex  → QuotaService.check_processing(tenant_id, plan)
```

## 模块设计

### 1. tenant/plan_presets.py

```python
PLAN_PRESETS: dict[str, dict] = {
    "free": { "features": {...}, "limits": {...} },
    "standard": { ... },
    "pro": { ... },
}
```

纯常量字典，零依赖。定义见 proposal 的 plan 三档表。

### 2. tenant/retrieve_presets.py

```python
RETRIEVE_PROFILE_PRESETS: dict[str, dict] = {
    "speed": { "mode": "vector", "top_k": 3, "rerank_enabled": False, "query_options": {"enabled": False} },
    "balanced": { "mode": "hybrid", "top_k": 5, "rerank_enabled": False, "query_options": {"enabled": False} },
    "quality": { "mode": "hybrid", "top_k": 8, "rerank_enabled": True, "rerank_top_n": 5, "query_options": {"enabled": True, "strategy": "rewrite"} },
}
```

不包含 "custom" — custom 走用户显式传入的 options。

### 3. tenant/plan_resolver.py

```python
@dataclass
class PlanContext:
    plan: str
    features: PlanFeatures
    limits: PlanLimits

def resolve_plan(plan: str) -> PlanContext:
    preset = PLAN_PRESETS.get(plan)
    if preset is None:
        raise ValueError(f"Unknown plan: {plan}")
    return PlanContext(plan=plan, features=PlanFeatures(**preset["features"]), limits=PlanLimits(**preset["limits"]))
```

纯函数，不涉及 Redis/DB。

### 4. services/rate_limit_service.py

```python
class RateLimitService:
    def __init__(self, redis: redis.asyncio.Redis): ...

    async def check_retrieve(self, tenant_id: str, plan: str) -> None:
        """QPS 限流 + 日配额检查。超限抛 AppError。"""
        # QPS: INCR rag:ratelimit:retrieve:{tid}:{unix_sec}, TTL 2s
        # 日配额: GET rag:quota:retrieve:daily:{tid}:{YYYYMMDD}

    async def record_retrieve_success(self, tenant_id: str) -> None:
        """检索成功后日计数 +1。"""
        # INCR rag:quota:retrieve:daily:{tid}:{YYYYMMDD}, TTL 25h
```

Redis 连接在 `composition.py` 的 lifespan 中创建：
```python
redis_client = redis.asyncio.from_url(cfg.CELERY_BROKER_URL, decode_responses=True)
rate_limiter = RateLimitService(redis_client)
```

### 5. services/quota_service.py

```python
class QuotaService:
    def __init__(self, pool: asyncpg.Pool): ...

    async def check_kb_count(self, tenant_id: str, plan: str) -> None: ...
    async def check_doc_upload(self, kb_id: str, tenant_id: str, plan: str) -> None: ...
    async def check_processing(self, tenant_id: str, plan: str) -> None: ...
```

SQL 查询：
- 库数: `SELECT count(*) FROM knowledge_bases WHERE tenant_id=$1`
- 单库文档数: `SELECT count(*) FROM documents WHERE kb_id=$1`
- 并发 PROCESSING: `SELECT count(*) FROM documents d JOIN knowledge_bases kb ON kb.id=d.kb_id WHERE kb.tenant_id=$1 AND d.status=2`

## 改动文件对照

| 现有文件 | 改动类型 | 改动量 |
|---------|---------|--------|
| `core/auth.py` | TenantContext 加 plan; _FALLBACK 默认 pro | +3 行 |
| `adapters/tenant/pg.py` | get_by_hash SQL 加 t.plan; get() 加 plan | +3 行 |
| `adapters/http/retrieve_router.py` | _RetrieveRequest + profile; handler + 展开逻辑 | +40 行 |
| `adapters/http/auth_router.py` | /auth/me 扩展 plan/features/limits/usage | +30 行 |
| `adapters/http/create_kb_router.py` | 建库配额检查 | +5 行 |
| `adapters/http/upload_doc_router.py` | 上传配额检查 | +8 行 |
| `adapters/http/document_router.py` | reindex 配额检查 | +5 行 |
| `core/errors.py` | +20013/20014; 20002→20005 | +6 行 |
| `domain/models.py` | Tenant + plan 字段 | +1 行 |
| `composition.py` | 创建 Redis 连接, 注入新服务, router 适配 | +25 行 |

| 新建文件 | 描述 |
|---------|------|
| `tenant/plan_presets.py` | ~50 行常量 |
| `tenant/retrieve_presets.py` | ~30 行常量 |
| `tenant/plan_resolver.py` | ~40 行 dataclass + 函数 |
| `tenant/__init__.py` | 空 |
| `services/rate_limit_service.py` | ~60 行 Redis 操作 |
| `services/quota_service.py` | ~50 行 DB 查询 |
| `services/__init__.py` | 空 |
| `scripts/update_tenant_plan.py` | ~40 行 CLI |

总计约 **400 行新代码**，改动用增量最小化原则。

## 关键约束

1. **Plan ceiling > .env**：profile 展开后的参数直接覆盖 uc.execute() 参数。free balanced 强制 `rerank_enabled=False`，不管 `.env` 的 `RERANK_ENABLED=true`
2. **日配额仅成功计数**：20013/20005 等错误不增加日配额计数器
3. **向后兼容**：不传 profile 默认 balanced，展开结果 = 当前默认行为 (hybrid, 无 rerank, 无 rewrite)
4. **AUTH_ENABLED=false**：`_FALLBACK_TENANT.plan = "pro"`，tenant_demo 享有全部功能
