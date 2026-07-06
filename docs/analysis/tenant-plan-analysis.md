# RAGNexus 租户套餐与配额系统 — 第一性原理分析

> 基于三篇飞书 Wiki 文档 + RAGNexus 现有代码库的深度对齐分析
>
> 分析时间：2026-07-06

---

## 一、第一性原理：这个需求在解决什么问题？

### 1.1 现状

```
所有租户 → 同一套检索默认值 → 谁都能无限建库、随意开 rerank
```

RAGNexus 当前的 `tenant` 只做**鉴权隔离**（`TenantContext` 里的 `tenant_id`）。`RetrieveUseCase` 的行为由 `.env` 的全局开关（`RERANK_ENABLED`、`REWRITE_ENABLED`、`RETRIEVAL_MODE`）和请求参数决定——每个租户拿到的是完全相同的"服务能力池"。

### 1.2 目标

```
tenant 从"鉴权标签" → 升级为"承载资源配额和功能开关的策略实体"
```

核心是把"租户能做什么"和"这次请求怎么跑"分开建模：

| 概念 | 粒度 | 数据来源 |
|------|------|---------|
| **plan（套餐）** | 租户级，三档 free/standard/pro | `tenants.plan` 列，脚本改 |
| **retrieve profile（检索预设）** | 请求级，四档 speed/balanced/quality/custom | 每次 `POST /v1/rag:retrieve` 传 |

### 1.3 本质

这不是一个新功能模块，而是**一层横切策略**，插入到现有 RAG 管道的请求入口：

```
请求 → [NEW] 读 plan → [NEW] 解析 profile → [NEW] 校验 + 展开
    → 现有检索管道（RetrieveUseCase）
    → [NEW] 日配额计数 → 响应含 tenant_policy
```

---

## 二、现有代码库全景（与需求的适配矩阵）

### 2.1 需要改动的文件（7 个后端 + 7 个前端）

| 文件 | 改动性质 | 原因 |
|------|---------|------|
| **`core/auth.py`** | 扩展现有 | `TenantContext` 加 `plan` 字段 |
| **`adapters/tenant/pg.py`** | 扩展现有 | `get_by_hash()` SQL 加 `t.plan` |
| **`adapters/http/retrieve_router.py`** | 扩展现有 | `_RetrieveRequest` 加 `profile`；handler 加 plan 校验 + profile 展开 |
| **`adapters/http/auth_router.py`** | 扩展现有 | `/auth/me` 返回 plan/features/limits/usage |
| **`core/errors.py`** | 扩展现有 | 加 `FEATURE_NOT_ALLOWED`(20013)、`QUOTA_EXCEEDED`(20014) |
| **`domain/models.py`** | 扩展现有 | `Tenant` dataclass 加 `plan` 字段 |
| **`composition.py`** | 扩展现有 | 注入 `PlanResolver`、`RateLimitService`、`QuotaService` |

### 2.2 需要新建的文件（6 个）

| 文件 | 职责 |
|------|------|
| **`tenant/plan_presets.py`** | 三档 plan 常量字典：features + limits |
| **`tenant/retrieve_presets.py`** | 四档 profile 展开规则：speed→vector, quality→hybrid+rerank+rewrite |
| **`tenant/plan_resolver.py`** | `PlanContext` dataclass + `resolve_plan(tenant)` |
| **`services/rate_limit_service.py`** | Redis QPS + 日配额计数 |
| **`services/quota_service.py`** | DB 配额检查（库数、文档数、并发索引） |
| **`scripts/update_tenant_plan.py`** | CLI 脚本：`--tenant-id --plan` |

### 2.3 Alembic 迁移

- 当前 head: `0006_document_status`
- 新迁移: `0007_tenant_plan` — `tenants` 表加 `plan VARCHAR(32) NOT NULL DEFAULT 'free'`
- 数据迁移: 升级前已存在的 tenant → `standard`；`tenant_demo` → `pro`

### 2.4 不动的东西

- chunk 表、documents 表、retrieve_logs 表
- `RetrieveUseCase.execute()` 签名（profile 在 router 层展开后透传现有参数）
- 词表 `settings.synonyms`（各 plan 都能用）
- Celery Worker 索引管道

---

## 三、核心架构决策

### 3.1 TenantContext 加 plan（推荐方案 A）

**理由**：`make_get_current_tenant` 里的 `get_by_hash()` 已经 `JOIN tenants`，`plan` 列顺路带回来零额外查询。

```python
# auth.py — TenantContext
@dataclass
class TenantContext:
    tenant_id: str
    tenant_name: str
    key_id: str
    key_prefix: str
    plan: str  # 新增 — free/standard/pro

# auth.py — get_by_hash() SQL 加一行
"""SELECT ..., t.plan AS tenant_plan FROM api_keys ak JOIN tenants t ..."""

# auth.py — _FALLBACK_TENANT (AUTH_ENABLED=false)
_FALLBACK_TENANT = TenantContext(..., plan="pro")  # tenant_demo 是 pro
```

### 3.2 Profile 展开放在 Router 层（不侵入 UseCase）

```
POST /v1/rag:retrieve { profile: "balanced", query: "...", kb_ids: [...] }
    │
    ▼
router 层 (retrieve_router.py):
  1. current_tenant.plan → PlanResolver.resolve_plan → PlanContext
  2. request.profile (默认 "balanced") → 校验 ∈ plan.features.allowed_profiles
  3. profile ≠ "custom" → RETRIEVE_PROFILE_PRESETS[profile] 展开为 options
  4. profile = "custom" → 用请求里的 options，过 plan ceiling 校验
  5. RateLimitService.check_retrieve(tenant_id, plan) — QPS/日配额
  6. → uc.execute(mode=..., rerank_enabled=..., query_options=...)  # 现有参数不变
    │
    ▼
RetrieveUseCase.execute() — 与现在完全一样
    │
    ▼
router 层:
  7. RateLimitService.record_retrieve_success(tenant_id) — 日配额 +1
  8. 响应 metadata.tenant_policy
```

**选择 router 层而非 use case 层的理由**：
- Profile 展开是"请求预处理"，不是业务编排
- `retrieve_presets.py` 是纯函数字典查找，无需 DI
- `RetrieveUseCase.execute()` 接口无需增加 profile 参数，向后兼容
- 只有 plan 校验和配额检查需要新服务——这些依赖通过 DI 注入 router

### 3.3 Plan ceiling 优先于 .env 全局开关

这是关键安全约束。profile 展开后的参数**覆盖**（而非叠加）传给 uc.execute() 的参数：

| profile | 传给 uc.execute() | 效果 |
|---------|------------------|------|
| speed | `mode="vector", rerank_enabled=False, query_options={"enabled":False}` | 不管 .env 的 `RERANK_ENABLED` |
| balanced | `mode="hybrid", rerank_enabled=False, query_options={"enabled":False}` | 同上 |
| quality (仅 pro) | `mode="hybrid", rerank_enabled=True, query_options={"enabled":True,"strategy":"rewrite"}` | 以 profile 为准 |
| custom | 用请求里显式传的 options，但过 plan ceiling | standard+custom+rerank → 20013 |

### 3.4 `/auth/me` 扩展

注入三个新依赖到 `create_auth_router`：

```python
async def auth_me(current_tenant=Depends(get_current_tenant)):
    plan_ctx = PlanResolver.resolve_plan(current_tenant.plan)
    # usage.kb_count → pool.fetchval("SELECT count(*) FROM knowledge_bases WHERE tenant_id=$1")
    # usage.retrieve_daily_count → Redis GET rag:quota:retrieve:daily:{tenant_id}:{YYYYMMDD}
    return {
        "tenant_id": ...,
        "plan": current_tenant.plan,
        "features": { ... },   # 来自 plan_presets
        "limits": { ... },     # 同上
        "usage": { "kb_count": ..., "retrieve_daily_count": ... }
    }
```

---

## 四、数据流：一次 retrieve 请求的 9 步

```
┌─────────────────────────────────────────────────────────────────┐
│  POST /v1/rag:retrieve  { query, kb_ids, profile? }              │
└────────────┬────────────────────────────────────────────────────┘
             │
    ┌────────▼────────┐
    │ 1. 鉴权          │  current_tenant = get_current_tenant()
    │                  │  → tenant_id + plan (从 get_by_hash JOIN 来)
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │ 2. 解析 plan     │  PlanResolver.resolve_plan(plan)
    │                  │  → PlanContext(features, limits)
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │ 3. 解析 profile  │  profile = request.profile or "balanced"
    │                  │  → 校验 profile ∈ features.allowed_profiles
    │                  │  → 否则抛 20013 FEATURE_NOT_ALLOWED
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │ 4. 展开 profile  │  profile ≠ "custom" → presets[profile] → options
    │ (非 custom)      │  profile = "custom" → 用请求 options
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │ 5. plan ceiling  │  对 custom: options 里的 rerank/rewrite/hybrid
    │ 校验             │  是否超出 plan.features 上限 → 20013
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │ 6. QPS 限流      │  RateLimitService.check_retrieve(tenant_id, plan)
    │                  │  → 超限抛 20005 API_RATE_LIMIT
    │                  │  → Redis key: rag:ratelimit:retrieve:{tid}:{unix_sec}
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │ 7. 日配额检查    │  Redis GET rag:quota:retrieve:daily:{tid}:{YYYYMMDD}
    │                  │  → ≥ limits.retrieve_daily → 20014 QUOTA_EXCEEDED
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │ 8. 检索管道      │  uc.execute(query, kb_ids, tenant_id, mode=..., rerank_enabled=...)
    │ (现有逻辑)       │  → RetrieveResult
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │ 9. 成功后        │  RateLimitService.record_retrieve_success(tenant_id)
    │ 日计数 +1        │  → Redis INCR rag:quota:retrieve:daily:{tid}:{YYYYMMDD}
    │ 响应             │  → 响应含 metadata.tenant_policy
    └─────────────────┘
```

---

## 五、三档 Plan 配置（硬编码常量）

```python
# src/ragnexus/tenant/plan_presets.py

PLAN_PRESETS = {
    "free": {
        "features": {
            "allowed_profiles": ["speed"],
            "hybrid_allowed": False,
            "rerank_allowed": False,
            "query_rewrite_allowed": False,
        },
        "limits": {
            "retrieve_qps": 3,
            "retrieve_daily": 500,
            "max_kb": 1,
            "max_documents_per_kb": 30,
            "max_processing_documents": 1,
        },
    },
    "standard": {
        "features": {
            "allowed_profiles": ["speed", "balanced", "custom"],
            "hybrid_allowed": True,
            "rerank_allowed": False,
            "query_rewrite_allowed": False,
        },
        "limits": {
            "retrieve_qps": 10,
            "retrieve_daily": 5_000,
            "max_kb": 5,
            "max_documents_per_kb": 200,
            "max_processing_documents": 2,
        },
    },
    "pro": {
        "features": {
            "allowed_profiles": ["speed", "balanced", "quality", "custom"],
            "hybrid_allowed": True,
            "rerank_allowed": True,
            "query_rewrite_allowed": True,
        },
        "limits": {
            "retrieve_qps": 50,
            "retrieve_daily": 100_000,
            "max_kb": 50,
            "max_documents_per_kb": 5_000,
            "max_processing_documents": 10,
        },
    },
}
```

---

## 六、四档 Profile 展开（硬编码常量）

```python
# src/ragnexus/tenant/retrieve_presets.py

RETRIEVE_PROFILE_PRESETS = {
    "speed": {
        "mode": "vector",
        "top_k": 3,
        "rerank_enabled": False,
        "query_options": {"enabled": False},
    },
    "balanced": {
        "mode": "hybrid",
        "top_k": 5,
        "rerank_enabled": False,
        "query_options": {"enabled": False},
    },
    "quality": {
        "mode": "hybrid",
        "top_k": 8,
        "rerank_enabled": True,
        "rerank_top_n": 5,
        "query_options": {"enabled": True, "strategy": "rewrite"},
    },
    # "custom" 不在此表中 — 走用户显式传入的 options
}
```

---

## 七、配额检查 SQL

### 7.1 库数上限（建库入口）

```python
count = await pool.fetchval(
    "SELECT count(*) FROM knowledge_bases WHERE tenant_id=$1", tenant_id
)
if count >= plan.limits.max_kb:
    raise AppError(ErrorCode.QUOTA_EXCEEDED, f"当前套餐仅支持 {plan.limits.max_kb} 个知识库")
```

### 7.2 单库文档数 + 并发 PROCESSING（上传入口）

```python
# 单库文档数
doc_count = await pool.fetchval(
    "SELECT count(*) FROM documents WHERE kb_id=$1", kb_id
)
if doc_count >= plan.limits.max_documents_per_kb:
    raise AppError(ErrorCode.QUOTA_EXCEEDED,
                   f"当前套餐单库仅支持 {plan.limits.max_documents_per_kb} 个文档")

# 租户并发 PROCESSING
processing_count = await pool.fetchval(
    "SELECT count(*) FROM documents d "
    "JOIN knowledge_bases kb ON kb.id = d.kb_id "
    "WHERE kb.tenant_id=$1 AND d.status=$2",
    tenant_id, DocStatus.PROCESSING.value,  # DocStatus.PROCESSING = 2
)
if processing_count >= plan.limits.max_processing_documents:
    raise AppError(ErrorCode.QUOTA_EXCEEDED, "当前套餐并发索引文档数已达上限，请稍后再试")
```

### 7.3 并发 PROCESSING（reindex 入口）

与 7.2 的 processing_count 查询相同，但入口在 reindex handler。

---

## 八、Redis 限流（复用 Celery Redis）

### 8.1 Key 设计

```
rag:ratelimit:retrieve:{tenant_id}:{unix_second}     # QPS, TTL 2s
rag:quota:retrieve:daily:{tenant_id}:{YYYYMMDD}       # 日配额, TTL 25h
```

### 8.2 QPS 检查

```python
async def check_qps(self, tenant_id: str, plan: str) -> None:
    limit = PLAN_PRESETS[plan]["limits"]["retrieve_qps"]
    second = int(time.time())
    key = f"rag:ratelimit:retrieve:{tenant_id}:{second}"
    count = await self.redis.incr(key)
    if count == 1:
        await self.redis.expire(key, 2)
    if count > limit:
        raise AppError(ErrorCode.API_RATE_LIMIT, f"检索 QPS 超限（{limit}/秒）")
```

### 8.3 日配额（仅成功后 +1）

```python
async def record_retrieve_success(self, tenant_id: str) -> None:
    date_str = datetime.now(UTC).strftime("%Y%m%d")
    key = f"rag:quota:retrieve:daily:{tenant_id}:{date_str}"
    await self.redis.incr(key)
    await self.redis.expire(key, 25 * 3600)  # 25h 跨零点容错
```

---

## 九、错误码扩展

```python
# src/ragnexus/core/errors.py — ErrorCode 枚举新增

# 套餐与配额 (20010~20019)
FEATURE_NOT_ALLOWED = (20013, 403, "当前套餐不支持此功能")
QUOTA_EXCEEDED = (20014, 429, "配额超限")
```

> 注意：现有 `API_RATE_LIMIT` 的 code 是 20002（不是文档说的 20005），但文档测试用例里写的 20005。这个不一致需要在实现时对齐——建议保留现有的 20002，或改为 20005 并更新所有引用。文档测试验收的 curl 预期用的是 20005，所以**改 ErrorCode 为 20005 是最小摩擦路径**。

---

## 十、前端改动清单

### 10.1 类型扩展

```typescript
// admin/src/types/api.ts — AuthMeData
export interface AuthMeData {
  tenant_id: string;
  tenant_name: string;
  key_id: string;
  key_prefix: string;
  plan: "free" | "standard" | "pro";           // 新增
  features: {                                    // 新增
    allowed_profiles: string[];
    hybrid_allowed: boolean;
    rerank_allowed: boolean;
    query_rewrite_allowed: boolean;
  };
  limits: {                                      // 新增
    retrieve_qps: number;
    retrieve_daily: number;
    max_kb: number;
    max_documents_per_kb: number;
    max_processing_documents: number;
  };
  usage: {                                       // 新增
    kb_count: number;
    retrieve_daily_count: number;
  };
}

// RetrieveRequest 加 profile
export interface RetrieveRequest {
  // ... 现有字段 ...
  profile?: "speed" | "balanced" | "quality" | "custom";  // 新增
}
```

### 10.2 改动文件

| 文件 | 改动 |
|------|------|
| `types/api.ts` | 扩展 `AuthMeData`；`RetrieveRequest` 加 `profile` |
| `services/authService.ts` | 类型适配 |
| `services/ragService.ts` | retrieve payload 带 `profile` |
| `pages/KnowledgeFileTreePage.tsx` | 顶栏加 plan badge |
| `pages/RetrievePage.tsx` | 四档 profile 选择器 + 置灰逻辑 + custom 联动 |
| `pages/KnowledgeUploadPage.tsx` | 捕获 20014，展示 msg |

### 10.3 交互规则

| 规则 | 实现 |
|------|------|
| profile 选择器 | Tab/Radio 四档，按 `features.allowed_profiles` 置灰不可用项 |
| 置灰 tooltip | "当前为标准套餐，不支持追求质量。如需使用请升级专业套餐。" |
| speed/balanced/quality | 折叠高级参数区，只传 `profile` |
| custom | 展开高级参数，各项按 plan ceiling 置灰 |
| plan badge | 免费(灰) / 标准(蓝) / 专业(紫/金) |
| 配额错误 | 上传页捕获 20014 展示 msg，不空白失败 |
| tenant_policy | 可选：结果区折叠展示生效参数 |

---

## 十一、实施路线图

```
Phase 1: 基础设施（1-2 个 commit）
├── 0007_tenant_plan migration
├── src/ragnexus/tenant/plan_presets.py
├── src/ragnexus/tenant/retrieve_presets.py
├── src/ragnexus/tenant/plan_resolver.py
└── src/ragnexus/tenant/__init__.py

Phase 2: 核心链路（2-3 个 commit）
├── TenantContext.plan + get_by_hash 加 plan
├── core/errors.py 加 20013/20014（修正 API_RATE_LIMIT 到 20005）
├── services/rate_limit_service.py
├── services/quota_service.py
├── retrieve_router.py: profile 解析 + plan 校验 + profile 展开
└── composition.py: DI 注入

Phase 3: API 扩展（1 个 commit）
├── auth_router.py: /auth/me 扩展
├── create_kb_router.py: 建库配额检查
├── upload_doc_router.py: 上传配额检查
├── document_router.py: reindex 配额检查
└── scripts/update_tenant_plan.py

Phase 4: 前端（2-3 个 commit）
├── types/api.ts: AuthMeData + RetrieveRequest 扩展
├── authService/ragService 适配
├── RetrievePage.tsx: profile 选择器 + 置灰 + custom 联动
├── KnowledgeFileTreePage.tsx: plan badge
├── KnowledgeUploadPage.tsx: 20014 错误处理
└── docs/tenant-onboarding.md

Phase 5: 测试验收
├── 迁移验证: alembic upgrade head + psql 查 tenants.plan
├── Profile 校验: free+speed✓ / free+balanced✗ / pro+quality✓ / standard+custom+rerank✗
├── 配额: free 建第二个库✗ / QPS 限流 / 日配额
├── /auth/me 完整字段
├── 跨租户隔离回归
└── 前端: 调试台四档 + badge + 配额错误
```

---

## 十二、关键风险与注意事项

| 风险 | 等级 | 缓解 |
|------|------|------|
| asyncpg JSONB 返回 str | 中 | quota_service 不涉及 JSONB；plan resolver 纯 Python dict，不受影响 |
| `API_RATE_LIMIT` code 不一致 | 中 | 现有 20002 → 改为 20005，greps 所有引用 |
| Docker 无热重载 | 低 | 改完代码 `docker compose build app`，AGENTS.md 已记录 |
| plan ceiling vs .env 优先级 | **高** | router 层 profile 展开后覆盖参数，不叠加；必须 code review 确认 custom 路径 |
| `api.ts` 和 `authService.ts` 双 `fetchAuthMe` | 低 | 统一用 `authService.ts` 版本，删 `api.ts` 里的 |
| AUTH_ENABLED=false 时的 plan | 低 | `_FALLBACK_TENANT.plan = "pro"` |
