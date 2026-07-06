# 租户套餐系统 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 RAGNexus Tenant 从鉴权标签升级为承载套餐+配额的策略实体，支持 free/standard/pro 三档

**Architecture:** 在 FastAPI 请求入口插入策略层（PlanResolver + RateLimitService + QuotaService），不侵入 RetrieveUseCase。Profile 在 router 层展开后透传现有 uc.execute() 参数

**Tech Stack:** Python 3.12, FastAPI, asyncpg, Redis (redis.asyncio), Alembic, React+TypeScript+Vite

**base-ref:** `2f7d2b7`

## Global Constraints

- Plan ceiling MUST 优先于 .env 全局开关；profile 展开后的参数直接覆盖 uc.execute() 参数
- 日配额仅在检索成功后 +1；失败/被拒绝不计数
- 不传 profile 默认 balanced，展开结果 = 当前默认行为（向后兼容）
- AUTH_ENABLED=false 时 _FALLBACK_TENANT.plan = "pro"
- 改完 Python 代码后 `docker compose build app && docker compose up -d app`
- asyncpg JSONB 返回 str 时需 `json.loads()`

## 文件地图

### 新建文件（8个）
| 文件 | 职责 | 估算行数 |
|------|------|---------|
| `src/ragnexus/tenant/__init__.py` | Package init | 1 |
| `src/ragnexus/tenant/plan_presets.py` | 三档 PLAN_PRESETS 常量 | ~50 |
| `src/ragnexus/tenant/retrieve_presets.py` | 四档 RETRIEVE_PROFILE_PRESETS | ~30 |
| `src/ragnexus/tenant/plan_resolver.py` | PlanContext + resolve_plan() | ~40 |
| `src/ragnexus/services/__init__.py` | Package init | 1 |
| `src/ragnexus/services/rate_limit_service.py` | Redis QPS + 日配额 | ~60 |
| `src/ragnexus/services/quota_service.py` | DB 配额检查 | ~50 |
| `scripts/update_tenant_plan.py` | CLI 脚本 | ~40 |
| `docs/tenant-onboarding.md` | 接入文档 | ~100 |
| `alembic/versions/0007_tenant_plan.py` | Migration | ~30 |

### 修改文件（10个）
| 文件 | 改动 | 估算行数 |
|------|------|---------|
| `domain/models.py` | Tenant + plan | +1 |
| `core/auth.py` | TenantContext + plan; _FALLBACK plan="pro" | +4 |
| `core/errors.py` | +20013/20014; 20002→20005 | +6 |
| `adapters/tenant/pg.py` | get_by_hash SQL + t.plan; get() + plan | +4 |
| `adapters/http/retrieve_router.py` | _RetrieveRequest + profile; handler | +50 |
| `adapters/http/auth_router.py` | /auth/me 扩展 | +35 |
| `adapters/http/create_kb_router.py` | 建库配额 | +8 |
| `adapters/http/upload_doc_router.py` | 上传配额 | +10 |
| `adapters/http/document_router.py` | reindex 配额 | +8 |
| `composition.py` | Redis + DI 注入 | +25 |

### 前端修改（7个）
| 文件 | 改动 |
|------|------|
| `admin/src/types/api.ts` | AuthMeData + RetrieveRequest 扩展 |
| `admin/src/services/authService.ts` | 类型适配 |
| `admin/src/services/ragService.ts` | retrieve 带 profile |
| `admin/src/services/api.ts` | 删除旧 fetchAuthMe |
| `admin/src/pages/RetrievePage.tsx` | profile 选择器 + 置灰 + custom 联动 |
| `admin/src/pages/KnowledgeFileTreePage.tsx` | plan badge |
| `admin/src/pages/KnowledgeUploadPage.tsx` | 20014 错误处理 |

---

## Task 1: Alembic 迁移

**Files:**
- Create: `alembic/versions/0007_tenant_plan.py`

- [x] **Step 1: 创建迁移文件**

```bash
cd F:/learnAgent/MyProjects/RAGNexus
uv run alembic revision -m "tenant_plan"
# 重命名生成的迁移文件为 0007_tenant_plan.py
```

- [x] **Step 2: 编写迁移**

```python
"""tenant_plan

Revision ID: <auto>
Revises: 0006_document_status
Create Date: <auto>
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '<auto>'
down_revision: Union[str, None] = '0006_document_status'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column('tenants', sa.Column('plan', sa.String(32), nullable=False, server_default='free'))
    # 已有租户升级为 standard; tenant_demo 升级为 pro
    op.execute("UPDATE tenants SET plan = 'standard' WHERE id NOT IN ('tenant_demo')")
    op.execute("UPDATE tenants SET plan = 'pro' WHERE id = 'tenant_demo'")
    # 移除 server_default 以让应用层控制默认值
    op.alter_column('tenants', 'plan', server_default=None)

def downgrade() -> None:
    op.drop_column('tenants', 'plan')
```

- [x] **Step 3: 执行迁移测试**

```bash
docker compose up -d db
uv run alembic upgrade head
docker exec ragnexus-db-1 psql -U ragnexus -d ragnexus -c "SELECT id, plan FROM tenants;"
```

- [x] **Step 4: Commit**

```bash
git add alembic/versions/0007_tenant_plan.py
git commit -m "feat(tenant): add plan column to tenants table (0007 migration)"
```

---

## Task 2: 领域模型与 plan_presets

**Files:**
- Create: `src/ragnexus/tenant/__init__.py`
- Create: `src/ragnexus/tenant/plan_presets.py`
- Create: `src/ragnexus/tenant/retrieve_presets.py`
- Create: `src/ragnexus/tenant/plan_resolver.py`
- Modify: `src/ragnexus/domain/models.py`

- [x] **Step 1: Tenant 模型加 plan 字段**

```python
# src/ragnexus/domain/models.py — Tenant dataclass
@dataclass
class Tenant:
    id: str
    name: str
    status: str = "active"
    plan: str = "free"  # 新增
    created_at: datetime | None = None
```

- [x] **Step 2: 创建 plan_presets.py**

```python
# src/ragnexus/tenant/plan_presets.py
PLAN_PRESETS = {
    "free": {
        "features": {
            "allowed_profiles": ["speed"],
            "hybrid_allowed": False, "rerank_allowed": False, "query_rewrite_allowed": False,
        },
        "limits": {
            "retrieve_qps": 3, "retrieve_daily": 500, "max_kb": 1,
            "max_documents_per_kb": 30, "max_processing_documents": 1,
        },
    },
    "standard": {
        "features": {
            "allowed_profiles": ["speed", "balanced", "custom"],
            "hybrid_allowed": True, "rerank_allowed": False, "query_rewrite_allowed": False,
        },
        "limits": {
            "retrieve_qps": 10, "retrieve_daily": 5000, "max_kb": 5,
            "max_documents_per_kb": 200, "max_processing_documents": 2,
        },
    },
    "pro": {
        "features": {
            "allowed_profiles": ["speed", "balanced", "quality", "custom"],
            "hybrid_allowed": True, "rerank_allowed": True, "query_rewrite_allowed": True,
        },
        "limits": {
            "retrieve_qps": 50, "retrieve_daily": 100000, "max_kb": 50,
            "max_documents_per_kb": 5000, "max_processing_documents": 10,
        },
    },
}
```

- [x] **Step 3: 创建 retrieve_presets.py**

```python
# src/ragnexus/tenant/retrieve_presets.py
RETRIEVE_PROFILE_PRESETS = {
    "speed": {"mode": "vector", "top_k": 3, "rerank_enabled": False, "query_options": {"enabled": False}},
    "balanced": {"mode": "hybrid", "top_k": 5, "rerank_enabled": False, "query_options": {"enabled": False}},
    "quality": {"mode": "hybrid", "top_k": 8, "rerank_enabled": True, "rerank_top_n": 5,
                "query_options": {"enabled": True, "strategy": "rewrite"}},
}
```

- [x] **Step 4: 创建 plan_resolver.py**

```python
# src/ragnexus/tenant/plan_resolver.py
from dataclasses import dataclass
from .plan_presets import PLAN_PRESETS

@dataclass
class PlanFeatures:
    allowed_profiles: list[str]
    hybrid_allowed: bool
    rerank_allowed: bool
    query_rewrite_allowed: bool

@dataclass
class PlanLimits:
    retrieve_qps: int
    retrieve_daily: int
    max_kb: int
    max_documents_per_kb: int
    max_processing_documents: int

@dataclass
class PlanContext:
    plan: str
    features: PlanFeatures
    limits: PlanLimits

def resolve_plan(plan: str) -> PlanContext:
    preset = PLAN_PRESETS.get(plan)
    if preset is None:
        raise ValueError(f"Unknown plan: {plan}")
    return PlanContext(
        plan=plan,
        features=PlanFeatures(**preset["features"]),
        limits=PlanLimits(**preset["limits"]),
    )
```

- [x] **Step 5: Commit**

```bash
git add src/ragnexus/tenant/ src/ragnexus/domain/models.py
git commit -m "feat(tenant): add plan presets, profile presets, plan resolver, and Tenant.plan field"
```

---

## Task 3: 错误码

**Files:**
- Modify: `src/ragnexus/core/errors.py`

- [x] **Step 1: 新增 FEATURE_NOT_ALLOWED 和 QUOTA_EXCEEDED；修正 API_RATE_LIMIT**

```python
# src/ragnexus/core/errors.py — ErrorCode 枚举
# 在 "接口与HTTP (20000~20999)" 区间新增：
FEATURE_NOT_ALLOWED = (20013, 403, "当前套餐不支持此功能")
QUOTA_EXCEEDED = (20014, 429, "配额超限")

# 修改现有 (原 20002):
API_RATE_LIMIT = (20005, 429, "接口调用超限")  # 从 20002 改为 20005
```

- [x] **Step 2: Grep 全量引用更新**

```bash
grep -rn "20002\|API_RATE_LIMIT" src/ tests/ --include="*.py"
# 确认所有引用点，更新测试用例中的预期 code
```

- [x] **Step 3: Commit**

```bash
git add src/ragnexus/core/errors.py
git commit -m "feat(tenant): add FEATURE_NOT_ALLOWED(20013) and QUOTA_EXCEEDED(20014); change API_RATE_LIMIT to 20005"
```

---

## Task 4: 鉴权扩展（TenantContext + plan）

**Files:**
- Modify: `src/ragnexus/core/auth.py`
- Modify: `src/ragnexus/adapters/tenant/pg.py`

- [x] **Step 1: TenantContext 加 plan**

```python
# src/ragnexus/core/auth.py
@dataclass
class TenantContext:
    tenant_id: str
    tenant_name: str
    key_id: str
    key_prefix: str
    plan: str  # 新增

_FALLBACK_TENANT = TenantContext(
    tenant_id="default", tenant_name="默认租户",
    key_id="fallback", key_prefix="none",
    plan="pro",  # AUTH_ENABLED=false 时 tenant_demo 享有 pro
)
```

- [x] **Step 2: get_by_hash SQL 加 plan；get() 加 plan**

```python
# src/ragnexus/adapters/tenant/pg.py — get_by_hash
"""SELECT ak.id::text AS key_id, ak.tenant_id, ..., t.plan AS tenant_plan
   FROM api_keys ak JOIN tenants t ON t.id = ak.tenant_id
   WHERE ak.key_hash = $1"""

# src/ragnexus/adapters/tenant/pg.py — get()
row = await self.pool.fetchrow(
    "SELECT id, name, status, plan, created_at FROM tenants WHERE id = $1", id
)
return Tenant(id=row["id"], name=row["name"], status=row["status"],
             plan=row["plan"], created_at=row["created_at"])
```

- [x] **Step 3: auth.py 赋值 plan**

```python
# make_get_current_tenant 第 134 行附近：
return TenantContext(
    tenant_id=key_record["tenant_id"],
    tenant_name=key_record["tenant_name"],
    key_id=key_record["key_id"],
    key_prefix=key_record["key_prefix"],
    plan=key_record.get("tenant_plan", "free"),  # 新增
)
```

- [x] **Step 4: Commit**

```bash
git add src/ragnexus/core/auth.py src/ragnexus/adapters/tenant/pg.py
git commit -m "feat(tenant): add plan field to TenantContext; get_by_hash returns plan via JOIN"
```

---

## Task 5: RateLimitService + QuotaService

**Files:**
- Create: `src/ragnexus/services/__init__.py`
- Create: `src/ragnexus/services/rate_limit_service.py`
- Create: `src/ragnexus/services/quota_service.py`

- [x] **Step 1: 创建 RateLimitService**

```python
# src/ragnexus/services/rate_limit_service.py
import time
from datetime import UTC, datetime
import redis.asyncio as aioredis
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.tenant.plan_presets import PLAN_PRESETS

class RateLimitService:
    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def check_retrieve(self, tenant_id: str, plan: str) -> None:
        limits = PLAN_PRESETS[plan]["limits"]
        # QPS
        second = int(time.time())
        qps_key = f"rag:ratelimit:retrieve:{tenant_id}:{second}"
        qps_count = await self._redis.incr(qps_key)
        if qps_count == 1:
            await self._redis.expire(qps_key, 2)
        if qps_count > limits["retrieve_qps"]:
            raise AppError(ErrorCode.API_RATE_LIMIT, f"检索 QPS 超限（{limits['retrieve_qps']}/秒）")
        # 日配额
        date_str = datetime.now(UTC).strftime("%Y%m%d")
        daily_key = f"rag:quota:retrieve:daily:{tenant_id}:{date_str}"
        daily_count = await self._redis.get(daily_key)
        if daily_count and int(daily_count) >= limits["retrieve_daily"]:
            raise AppError(ErrorCode.QUOTA_EXCEEDED, f"日检索量已达上限（{limits['retrieve_daily']}次/天）")

    async def record_retrieve_success(self, tenant_id: str) -> None:
        date_str = datetime.now(UTC).strftime("%Y%m%d")
        key = f"rag:quota:retrieve:daily:{tenant_id}:{date_str}"
        await self._redis.incr(key)
        await self._redis.expire(key, 25 * 3600)

    async def get_daily_count(self, tenant_id: str) -> int:
        """查询租户当日检索量（供 /auth/me 使用）。"""
        from datetime import UTC, datetime
        date_str = datetime.now(UTC).strftime("%Y%m%d")
        val = await self._redis.get(f"rag:quota:retrieve:daily:{tenant_id}:{date_str}")
        return int(val) if val else 0
```

- [x] **Step 2: 创建 QuotaService**

```python
# src/ragnexus/services/quota_service.py
import asyncpg
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import DocStatus
from ragnexus.tenant.plan_presets import PLAN_PRESETS

class QuotaService:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def check_kb_count(self, tenant_id: str, plan: str) -> None:
        limit = PLAN_PRESETS[plan]["limits"]["max_kb"]
        count = await self._pool.fetchval(
            "SELECT count(*) FROM knowledge_bases WHERE tenant_id=$1", tenant_id
        )
        if count >= limit:
            raise AppError(ErrorCode.QUOTA_EXCEEDED, f"当前套餐仅支持 {limit} 个知识库")

    async def check_doc_upload(self, kb_id: str, tenant_id: str, plan: str) -> None:
        limits = PLAN_PRESETS[plan]["limits"]
        # 单库文档数
        doc_count = await self._pool.fetchval(
            "SELECT count(*) FROM documents WHERE kb_id=$1", kb_id
        )
        if doc_count >= limits["max_documents_per_kb"]:
            raise AppError(ErrorCode.QUOTA_EXCEEDED, f"单库最多 {limits['max_documents_per_kb']} 个文档")
        # 并发 PROCESSING
        await self.check_processing(tenant_id, plan)

    async def check_processing(self, tenant_id: str, plan: str) -> None:
        limit = PLAN_PRESETS[plan]["limits"]["max_processing_documents"]
        count = await self._pool.fetchval(
            "SELECT count(*) FROM documents d JOIN knowledge_bases kb ON kb.id=d.kb_id "
            "WHERE kb.tenant_id=$1 AND d.status=$2",
            tenant_id, DocStatus.PROCESSING.value,
        )
        if count >= limit:
            raise AppError(ErrorCode.QUOTA_EXCEEDED, "并发索引文档数已达上限，请稍后再试")
```

- [x] **Step 3: Commit**

```bash
git add src/ragnexus/services/
git commit -m "feat(tenant): add RateLimitService (Redis QPS+daily) and QuotaService (DB limits)"
```

---

## Task 6: Retrieve Router 改造（核心链路）

**Files:**
- Modify: `src/ragnexus/adapters/http/retrieve_router.py`
- Modify: `src/ragnexus/composition.py`

- [x] **Step 1: _RetrieveRequest 加 profile 字段**

```python
# retrieve_router.py — _RetrieveRequest
profile: Literal["speed", "balanced", "quality", "custom"] | None = None  # 新增
```

- [x] **Step 2: create_router 注入新依赖**

```python
def create_router(uc, get_current_tenant, rate_limiter=None, quota_svc=None) -> APIRouter:
```

- [x] **Step 3: Handler 插入 plan 校验 + profile 展开**

在 `retrieve()` handler 中，`uc.execute()` 之前插入：

```python
from ragnexus.tenant.plan_resolver import resolve_plan
from ragnexus.tenant.retrieve_presets import RETRIEVE_PROFILE_PRESETS
from ragnexus.core.errors import AppError, ErrorCode

plan_ctx = resolve_plan(current_tenant.plan)
profile = req.profile or "balanced"
if profile not in plan_ctx.features.allowed_profiles:
    raise AppError(ErrorCode.FEATURE_NOT_ALLOWED,
                   f"当前套餐 {current_tenant.plan} 不支持检索预设 {profile}")

if profile != "custom":
    preset = RETRIEVE_PROFILE_PRESETS[profile]
    mode = preset["mode"]
    top_k = preset["top_k"]
    rerank_enabled = preset.get("rerank_enabled", False)
    rerank_top_n = preset.get("rerank_top_n", 5)
    query_options_dict = preset.get("query_options")
else:
    # custom: 用请求 options，校验 plan ceiling
    mode = req.mode
    top_k = req.top_k
    rerank_enabled = req.rerank.enabled if req.rerank else None
    rerank_top_n = req.rerank.top_n if req.rerank else 5
    query_options_dict = req.query_options.model_dump(exclude_unset=True) if req.query_options else None
    if rerank_enabled and not plan_ctx.features.rerank_allowed:
        raise AppError(ErrorCode.FEATURE_NOT_ALLOWED, "当前套餐不支持 rerank")
    if mode == "hybrid" and not plan_ctx.features.hybrid_allowed:
        raise AppError(ErrorCode.FEATURE_NOT_ALLOWED, "当前套餐不支持 hybrid 检索")
    if query_options_dict and query_options_dict.get("enabled") and not plan_ctx.features.query_rewrite_allowed:
        raise AppError(ErrorCode.FEATURE_NOT_ALLOWED, "当前套餐不支持 query 改写")

# QPS + 日配额
if rate_limiter:
    await rate_limiter.check_retrieve(current_tenant.tenant_id, current_tenant.plan)

# --- 走现有检索 ---
result = await uc.execute(query=req.query, kb_ids=req.kb_ids,
    tenant_id=current_tenant.tenant_id, top_k=top_k, mode=mode,
    vector_top_k=req.vector_top_k, bm25_top_k=req.bm25_top_k, rrf_k=req.rrf_k,
    rerank_enabled=rerank_enabled, rerank_top_n=rerank_top_n,
    query_options=query_options_dict)

# 日计数 +1
if rate_limiter:
    await rate_limiter.record_retrieve_success(current_tenant.tenant_id)
```

- [x] **Step 4: 响应加 tenant_policy**

```python
"meta": {
    ...,
    "tenant_policy": {
        "plan": current_tenant.plan,
        "retrieve_profile": profile,
        "effective_mode": mode,
        "effective_rerank": rerank_enabled or False,
        "effective_query_rewrite": bool(query_options_dict and query_options_dict.get("enabled")),
    },
}
```

- [x] **Step 5: composition.py 注入**

```python
import redis.asyncio as aioredis
from ragnexus.services.rate_limit_service import RateLimitService
from ragnexus.services.quota_service import QuotaService

# lifespan 中:
redis_client = aioredis.from_url(cfg.CELERY_BROKER_URL, decode_responses=True)
rate_limiter = RateLimitService(redis_client)
quota_svc = QuotaService(pool=cast(Any, repo_pool))

# router:
app.include_router(create_retrieve_router(retrieve_uc, get_current_tenant, rate_limiter))
```

- [x] **Step 6: Commit**

```bash
git add src/ragnexus/adapters/http/retrieve_router.py src/ragnexus/composition.py
git commit -m "feat(tenant): integrate plan enforcement + profile expansion + rate limiting into retrieve router"
```

---

## Task 7: 配额入口接入

**Files:**
- Modify: `src/ragnexus/adapters/http/create_kb_router.py`
- Modify: `src/ragnexus/adapters/http/upload_doc_router.py`
- Modify: `src/ragnexus/adapters/http/document_router.py`
- Modify: `src/ragnexus/composition.py`

- [x] **Step 1: create_kb_router 加配额**

```python
# 注入 quota_svc; handler 开头:
await quota_svc.check_kb_count(current_tenant.tenant_id, current_tenant.plan)
```

- [x] **Step 2: upload_doc_router 加配额**

```python
# 注入 quota_svc; handler 中 uc.execute() 之前:
await quota_svc.check_doc_upload(kb_id, current_tenant.tenant_id, current_tenant.plan)
```

- [x] **Step 3: document_router(reindex) 加配额**

```python
# reindex handler 中:
await quota_svc.check_processing(current_tenant.tenant_id, current_tenant.plan)
```

- [x] **Step 4: composition.py 注入 quota_svc 到对应 router**

```bash
git add src/ragnexus/adapters/http/create_kb_router.py \
        src/ragnexus/adapters/http/upload_doc_router.py \
        src/ragnexus/adapters/http/document_router.py \
        src/ragnexus/composition.py
git commit -m "feat(tenant): add quota checks to create KB, upload doc, and reindex endpoints"
```

---

## Task 8: /auth/me 扩展

**Files:**
- Modify: `src/ragnexus/adapters/http/auth_router.py`
- Modify: `src/ragnexus/composition.py`

- [x] **Step 1: 注入 tenant_repo 和 rate_limiter**

```python
def create_auth_router(get_current_tenant, tenant_repo=None, rate_limiter=None) -> APIRouter:
```

- [x] **Step 2: /auth/me 扩展返回**

```python
from ragnexus.tenant.plan_presets import PLAN_PRESETS
from ragnexus.tenant.plan_resolver import resolve_plan
from datetime import UTC, datetime

plan_ctx = resolve_plan(current_tenant.plan)
# usage.kb_count 查 DB
kb_count = 0
if tenant_repo:
    kb_count = await tenant_repo.pool.fetchval(
        "SELECT count(*) FROM knowledge_bases WHERE tenant_id=$1", current_tenant.tenant_id
    ) or 0
# usage.retrieve_daily_count 查 Redis
# usage.retrieve_daily_count 通过公开方法查询
daily_count = 0
if rate_limiter:
    daily_count = await rate_limiter.get_daily_count(current_tenant.tenant_id)

return {
    "tenant_id": current_tenant.tenant_id,
    "tenant_name": current_tenant.tenant_name,
    "plan": current_tenant.plan,
    "features": plan_ctx.features.__dict__,
    "limits": plan_ctx.limits.__dict__,
    "usage": {"kb_count": kb_count, "retrieve_daily_count": daily_count},
}
```

- [x] **Step 3: Commit**

```bash
git add src/ragnexus/adapters/http/auth_router.py src/ragnexus/composition.py
git commit -m "feat(tenant): extend /auth/me with plan, features, limits, and usage fields"
```

---

## Task 9: 运维脚本 + 接入文档

**Files:**
- Create: `scripts/update_tenant_plan.py`
- Create: `docs/tenant-onboarding.md`

- [x] **Step 1: update_tenant_plan.py**

```python
import argparse, asyncio, asyncpg, os, sys
VALID_PLANS = {"free", "standard", "pro"}

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--plan", required=True)
    args = parser.parse_args()
    if args.plan not in VALID_PLANS:
        print(f"错误: plan 必须是 {VALID_PLANS} 之一", file=sys.stderr)
        sys.exit(1)
    dsn = os.environ.get("PG_DSN", "postgresql://ragnexus:ragnexus@localhost:5432/ragnexus")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
    try:
        exists = await pool.fetchval("SELECT 1 FROM tenants WHERE id=$1", args.tenant_id)
        if not exists:
            print(f"错误: 租户 {args.tenant_id} 不存在，请先运行 create_tenant.py", file=sys.stderr)
            sys.exit(1)
        await pool.execute("UPDATE tenants SET plan=$1 WHERE id=$2", args.plan, args.tenant_id)
        print(f"租户 plan 已更新: id={args.tenant_id} plan={args.plan}")
    finally:
        await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
```

- [x] **Step 2: tenant-onboarding.md**

- [x] **Step 3: Commit**

```bash
git add scripts/update_tenant_plan.py docs/tenant-onboarding.md
git commit -m "feat(tenant): add update_tenant_plan script and tenant-onboarding.md"
```

---

## Task 10: 前端适配

- [x] **10.1 types/api.ts** — AuthMeData 扩展 plan/features/limits/usage；RetrieveRequest + profile
- [x] **10.2 authService.ts + ragService.ts** — 类型适配，retrieve 带 profile
- [x] **10.3 api.ts** — 删除旧 fetchAuthMe，统一用 authService.ts
- [x] **10.4 RetrievePage.tsx** — profile 选择器 + 置灰 + 折叠高级参数 + custom 联动 + tenant_policy 展示
- [x] **10.5 KnowledgeFileTreePage.tsx** — 顶栏 plan badge
- [x] **10.6 KnowledgeUploadPage.tsx** — 捕获 20014 展示 msg

```bash
git add admin/src/types/api.ts admin/src/services/ admin/src/pages/
git commit -m "feat(frontend): add profile selector, plan badge, and quota error handling"
```

---

## Task 11: 测试与验证

- [x] **11.1 单元测试**
- [x] **11.2 集成测试**
- [x] **11.3 E2E**
- [x] **11.4 Docker 重建验证**
- [x] **11.5 路由完整性**
