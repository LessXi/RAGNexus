# Design: 多租户鉴权

> 融合分析：[docs/superpowers/analysis/2026-07-04-multi-tenant-auth-fusion.md](../../docs/superpowers/analysis/2026-07-04-multi-tenant-auth-fusion.md)
> 提案：[proposal.md](./proposal.md)

## 架构决策

### ADR-1：API Key + Bearer Token 方案

| 维度 | 决策 |
|---|---|
| 认证方式 | API Key（`rk_live_<32位hex>`），Bearer Token 传递 |
| 存储 | SHA-256 hash 存入 `api_keys.key_hash`，明文仅在创建时终端打印一次 |
| 校验 | FastAPI `Depends(get_current_tenant)` 统一入口，返回 `TenantContext` |
| 降级 | `AUTH_ENABLED=false` 时跳过验 Key，固定占位租户 `default` |

### ADR-2：FK 约束策略

`knowledge_bases.tenant_id` 加 `FOREIGN KEY REFERENCES tenants(id) ON DELETE RESTRICT`。

理由：
- **RESTRICT**：有 KB 时不允许删租户，防止孤儿数据 → 隔离失效
- 拒绝 **CASCADE**：删租户自动级联删 KB/documents/chunks/向量，生产事故风险高
- 拒绝 **NO FK**：语义上违反"租户拥有知识库"的领域约束

### ADR-3：错误码沿用 10200

项目已有 `ErrorCode.UNAUTHORIZED = (10200, 401, "未授权，请登录")`，在认证区间 10200-10299。沿用不改。

提示词建议 code 20010 + HTTP 200，但改动全局 error_handler 影响所有 33 个错误码，风险远大于收益。401 HTTP 状态码语义准确，前端拦截器同时处理 401 状态和 10200 body code 零额外成本。

### ADR-4：跨租户资源拒绝策略

upload/retrieve 接口收到其他租户的 kb_id 时，返回 `FORBIDDEN (10201)` 而非 `NOT_FOUND (10300)`。

理由：KB 存在但不属于你，返回 NOT_FOUND 会误导调用方反复重试。FORBIDDEN 明确告知"这不是你的数据"。upload 和 retrieve 共享同一校验逻辑，分别在 `UploadDocumentUseCase` 和 `RetrieveUseCase` 入口处执行。

### ADR-5：前端 API_KEY 暴露本期接受

`import.meta.env.API_KEY` 会被 Vite 打包进 JS bundle，前端源码可见。对内部管理 SPA（内网部署）可接受。下期独立 change 引入 session token 机制（后端签发短期 JWT，前端用 API Key 换 token）。

### ADR-6：Depends 依赖注入机制

`get_current_tenant` 需要访问 TenantRepository 和 ApiKeyRepository（数据库连接池），但项目不通过全局变量或 `app.state` 传递依赖。

采用**工厂函数闭包注入**模式，与现有 Router 工厂模式一致：

```python
# core/auth.py — 返回 Depends callable
def make_get_current_tenant(
    tenant_repo: TenantRepository,
    api_key_repo: ApiKeyRepository,
    auth_enabled: bool,
):
    """返回 get_current_tenant Depends，通过闭包注入 repo 和配置。"""
    async def get_current_tenant(
        authorization: str | None = Header(None),
    ) -> TenantContext:
        if not auth_enabled:
            return TenantContext(
                tenant_id="default",
                tenant_name="默认租户",
                key_id="",
                key_prefix="",
            )
        if authorization is None:
            raise AppError(UNAUTHORIZED, "缺少 Authorization 请求头")
        token = extract_token(authorization)  # 去掉 "Bearer " 前缀
        key_hash = hash_key(token)            # SHA-256
        record = await api_key_repo.by_hash(key_hash)  # JOIN tenants
        if record is None:
            raise AppError(UNAUTHORIZED, "API Key 无效")
        # 校验 status/expires_at/tenant.status ...
        return TenantContext(...)
    return get_current_tenant
```

`composition.py` 在 lifespan 中创建 repo 后调用一次，传入所有 5 个 Router 工厂：

```python
get_current_tenant_dep = make_get_current_tenant(
    tenant_repo, api_key_repo, settings.AUTH_ENABLED
)

app.include_router(create_auth_router(get_current_tenant_dep))
app.include_router(create_kb_router(uc, get_current_tenant_dep))
app.include_router(create_kb_tree_router(uc, get_current_tenant_dep))
app.include_router(create_upload_doc_router(uc, get_current_tenant_dep))
app.include_router(create_retrieve_router(uc, get_current_tenant_dep))
```

**要点**：
- `Depends(get_current_tenant)` 中的 `get_current_tenant` 是工厂函数返回的闭包，而非模块级函数
- `TenantContext` 是 dataclass，FastAPI Depends 默认 `use_cache=True` 在同一请求中复用结果，依赖 FastAPI 的 callable 实例缓存而非 dataclass 的 `__hash__`
- Router 工厂签名统一为 `(uc, get_current_tenant)`，与现有 `(uc)` 模式一致的增量变化

## 组件设计

### 后端新增文件

```
src/ragnexus/
├── core/
│   └── auth.py              # TenantContext + make_get_current_tenant + hash/extract 纯函数
├── domain/
│   └── models.py            # 新增 Tenant, ApiKey dataclass
├── adapters/
│   ├── tenant/
│   │   ├── __init__.py
│   │   └── pg.py            # PgTenantRepository + PgApiKeyRepository
│   └── http/
│       ├── auth_router.py   # GET /v1/auth/me
│       └── deps.py          # 重新导出 make_get_current_tenant（alias 供 composition 使用）
├── config.py                # 新增 AUTH_ENABLED
└── composition.py           # 新增 auth 依赖装配（修改所有 5 个 Router 工厂调用）

scripts/
├── create_tenant.py         # 注册租户
└── create_api_key.py        # 给租户发 Key

alembic/versions/
└── 0003_multi_tenant_auth.py  # tenants + api_keys 表 + FK + 索引
```

### 数据模型

```
┌─ tenants ─────────────────┐     ┌─ api_keys ───────────────────────┐
│ id (PK)      TEXT         │◄────│ tenant_id   TEXT FK(tenants.id)  │
│ name         TEXT         │     │ id (PK)     UUID                 │
│ status       TEXT         │     │ key_hash    TEXT UNIQUE          │
│ created_at   TIMESTAMPTZ  │     │ key_prefix  TEXT                 │
└───────────────────────────┘     │ name        TEXT                 │
                                  │ status      TEXT                 │
                                  │ expires_at  TIMESTAMPTZ?         │
                                  │ created_at  TIMESTAMPTZ          │
                                  └──────────────────────────────────┘
                                  索引：idx_api_keys_tenant ON (tenant_id)

knowledge_bases.tenant_id: FK → tenants.id ON DELETE RESTRICT
```

### TenantContext

```python
@dataclass
class TenantContext:
    tenant_id: str       # 鉴权通过后的租户 ID
    tenant_name: str     # 租户展示名
    key_id: str          # api_keys.id (UUID)
    key_prefix: str      # 如 "rk_a1b2"，日志辨认用
```

### key_prefix 截取规则

完整 Key 格式：`rk_live_<32位hex>`，如 `rk_live_a1b2c3d4e5f67890abcdef12345678`

前缀截取：`"rk_" + 随机 hex 的前 4 位` → `"rk_a1b2"`（取完整 32 位 hex 中 `secrets.token_hex(16)` 生成值的前 4 个字符）

前缀不包含 `live_` 部分，避免日志中暴露 Key 版本/类型信息。

### AUTH_ENABLED=false 时 TenantContext 字段来源

| 字段 | 值 | 来源 |
|---|---|---|
| `tenant_id` | `"default"` | 硬编码，与存量数据一致 |
| `tenant_name` | `"默认租户"` | 硬编码（不查 DB，零依赖） |
| `key_id` | `""` | 空字符串（无 Key） |
| `key_prefix` | `""` | 空字符串（无 Key） |

### get_current_tenant 校验流程

```
Authorization header
  ↓
AUTH_ENABLED?
  ├─ false → 返回 TenantContext(tenant_id="default", ...) 占位
  └─ true  → header 存在？
              ├─ 否 → 401 UNAUTHORIZED（缺少 Authorization 请求头）
              └─ 是 → 格式 "Bearer <token>"？
                      ├─ 否 → 401 UNAUTHORIZED（Authorization 格式错误）
                      └─ 是 → SHA-256(token)
                              ↓
                            SELECT api_keys.*, tenants.*
                            FROM api_keys JOIN tenants ON api_keys.tenant_id = tenants.id
                            WHERE api_keys.key_hash = $1
                              ↓
                            ├─ 不存在 → 401 UNAUTHORIZED
                            ├─ key.status = 'revoked' → 401 UNAUTHORIZED
                            ├─ key.expires_at < now() → 401 UNAUTHORIZED
                            ├─ tenant.status = 'disabled' → 401 UNAUTHORIZED
                            └─ 通过 → 返回 TenantContext
```

### 业务接口接入模式

每个需要鉴权的路由函数新增 Depends 参数：

```python
tenant: TenantContext = Depends(get_current_tenant)
```

路由函数内部用 `tenant.tenant_id` 替换原来的 `req.tenant_id`。

**四个接口的具体变更**：

| 接口 | Router | UseCase | 校验 |
|---|---|---|---|
| create KB | 去 `tenant_id` body 字段 | `tenant_id` 从 Depends 注入 | 无额外校验 |
| tree | keyword 语义从匹配 tenant_id → 匹配 KB 名称 | 签名加 `tenant_id` | Repo 改 `WHERE tenant_id = $1 AND name ILIKE $2` |
| upload | 加 `get_current_tenant` 参数 | 签名加 `tenant_id` | **新增**：`kb.tenant_id != tenant_id → FORBIDDEN` |
| retrieve | 加 `get_current_tenant` 参数 | 新增 `validate_kb_ownership` | **新增**：`set(kb_ids)` 去重后 COUNT 对比 → FORBIDDEN |

### 前端新增/修改文件

```
admin/
├── src/
│   ├── lib/
│   │   └── axios.ts            # 修改：请求拦截器 Bearer + 响应/错误双拦截器 10200 处理
│   ├── types/
│   │   └── api.ts              # 修改：Request 去 tenant_id，新增 AuthMeData
│   ├── services/
│   │   ├── api.ts              # 修改：payload 不传 tenant_id
│   │   └── authService.ts      # 新增：fetchAuthMe()
│   └── pages/
│       ├── upload-doc.tsx       # 修改：去 tenant_id 输入
│       ├── knowledge-file-tree.tsx  # 修改：三级→两级 + badge
│       └── retrieve.tsx         # 修改：去租户筛选 + HelpTooltip
├── .env.example                 # 新增
├── .gitignore                   # 确认含 .env
└── vite.config.ts               # 修改：envPrefix
```

## 数据流

### 鉴权成功路径（以创建 KB 为例）

```
前端 .env API_KEY → 拦截器自动加 Header
   ↓ POST /v1/knowledge-bases:create {"name":"test"}
FastAPI Depends(get_current_tenant)
   ↓ SHA-256 → DB 查 hash → 查 tenant → TenantContext
Router: tenant.tenant_id = "tenant_demo"
   ↓
UseCase.execute(name="test", tenant_id=tenant.tenant_id)
   ↓
Repo: INSERT INTO knowledge_bases (name, tenant_id) VALUES ('test', 'tenant_demo')
   ↓
Response: {"code":0, "data":{"kb_id":"kb_xxx", "tenant_id":"tenant_demo"}}
```

### AUTH_ENABLED=false 降级路径

```
前端 .env API_KEY 留空 → 拦截器不传 Header
   ↓ POST /v1/knowledge-bases:create {"name":"test"}
FastAPI Depends(get_current_tenant)
   ↓ AUTH_ENABLED=false → 不查 DB
   ↓ 构造 TenantContext(tenant_id="default", tenant_name="默认租户", key_id="", key_prefix="")
Router: tenant.tenant_id = "default"
   ↓ ... 后续同正常路径
```

### 跨租户拒绝路径（以 upload 为例）

```
Key A (tenant_a) → POST /v1/documents:upload kb_id=xxx
   ↓
FastAPI Depends(get_current_tenant) → TenantContext(tenant_id="tenant_a")
   ↓
UseCase.execute(kb_id="xxx", tenant_id="tenant_a")
   ↓ kb = repo.get("xxx")  → kb.tenant_id = "tenant_b"
   ↓ kb.tenant_id != tenant.tenant_id → FORBIDDEN (10201)
Response: HTTP 403 {"code":10201, "message":"权限不足"}
```

## 存量数据迁移

迁移 0003 自动处理：
1. 创建 `tenants` 表
2. `INSERT INTO tenants (id, name, status) VALUES ('default', '默认租户（迁移）', 'active')`
3. 扫描 `SELECT DISTINCT tenant_id FROM knowledge_bases WHERE tenant_id IS NOT NULL AND tenant_id != ''`，对不在 tenants 中的 tenant_id 逐个插入
4. 创建 `api_keys` 表（含 `idx_api_keys_tenant` 索引）
5. 加 FK 约束 `knowledge_bases.tenant_id → tenants.id ON DELETE RESTRICT`

AUTH_ENABLED=false 时的占位租户用 `default`，与存量数据一致。

## 迁移降级策略

```sql
-- downgrade: 先删 FK 约束，再删表
ALTER TABLE knowledge_bases DROP CONSTRAINT IF EXISTS fk_kb_tenant;
DROP TABLE IF EXISTS api_keys;
DROP TABLE IF EXISTS tenants;
```

降级后 `knowledge_bases.tenant_id` 恢复为无 FK 约束的 TEXT 字段，存量值（如 `'default'`）保持不变，业务接口仍可通过旧代码（无鉴权模式）正常访问。
