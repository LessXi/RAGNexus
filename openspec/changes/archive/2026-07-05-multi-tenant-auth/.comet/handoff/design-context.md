# Comet Design Handoff

- Change: multi-tenant-auth
- Phase: design
- Mode: compact
- Context hash: 75048076148dce22a92e620a630aa340273908ae7dc2a47d4612a10b65f65960

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/multi-tenant-auth/proposal.md

- Source: openspec/changes/multi-tenant-auth/proposal.md
- Lines: 1-45
- SHA256: ee80ce7031600c8bced9a1e6d8359e28fa37e329826f2e99c64bf62567401dd6

```md
# Proposal: 多租户鉴权

> 融合分析：[docs/superpowers/analysis/2026-07-04-multi-tenant-auth-fusion.md](../../docs/superpowers/analysis/2026-07-04-multi-tenant-auth-fusion.md)

## Why

当前 RAGNexus 的 `tenant_id` 由客户端在请求体中传入，服务端直接信任。任何人猜到其他租户 ID 即可读写对方数据。作为对外提供能力的 RAG 中台，必须实现基于 API Key 的多租户鉴权隔离，让服务端派生租户身份，客户端无法伪造。

## What Changes

### 后端 — Phase 1：鉴权地基

- **BREAKING**: 新增 `tenants`、`api_keys` 两张表（Alembic 0003 迁移），`knowledge_bases.tenant_id` 加 FK → `tenants.id` ON DELETE RESTRICT
- 新增 `Tenant`、`ApiKey` 领域模型（dataclass）及对应 PgRepository
- 新增 `core/auth.py`：`TenantContext` + `get_current_tenant` Depends + SHA-256 Key 校验
- 新增 `GET /v1/auth/me` 端点，供调用方验证 Key 有效性
- 新增 `AUTH_ENABLED` 配置项（默认 true），`false` 时跳过验 Key 用占位租户 `default`
- 新增运维脚本 `scripts/create_tenant.py` + `scripts/create_api_key.py`
- 错误码沿用现有 `UNAUTHORIZED = 10200 (HTTP 401)`

### 后端 — Phase 2：业务接口接入

- **BREAKING**: `POST /v1/knowledge-bases:create` 请求体移除 `tenant_id`，由 Key 派生注入
- **BREAKING**: `GET /v1/knowledge-bases/tree` 改为只返回当前租户数据（单租户数组），keyword 语义从「匹配 tenant_id」改为「匹配知识库名称」
- `POST /v1/documents:upload` 无改动（本来就不传 tenant_id）
- `POST /v1/rag:retrieve` 新增 kb_ids 归属校验，跨租户 kb_id → `FORBIDDEN (10201)`

### 前端 — Phase 3：去 tenant_id 适配

- `http.ts` 新增请求/响应拦截器：自动带 Bearer Key、拦截 code 10200 错误提示
- 三个页面移除 `tenant_id` 输入/筛选，列表页三级树改为两级 + 租户 badge
- types/services 新增 `authService.ts`/`AuthMeData`，Request 类型移除 `tenant_id`
- 新增 `frontend/.env.example` 含 `API_KEY`，vite.config.ts 加 `envPrefix`

## Capabilities

### New Capabilities

- `multi-tenant-auth-backend`: 租户管理（tenants/api_keys 表、模型、仓库、运维脚本）、API Key 鉴权（生成/校验/SHA-256 存储）、FastAPI Depends 注入、AUTH_ENABLED 开关、/auth/me 验证端点
- `multi-tenant-auth-frontend`: 请求拦截器自动带 Key、响应拦截 10200 错误提示、三级树→两级树 UI、租户 badge、HelpTooltip 组件

### Modified Capabilities

- `knowledge-base-crud`: create 请求体移除 tenant_id，tree 按租户过滤
- `rag-retrieval`: 新增 kb_ids 租户归属校验
```

## openspec/changes/multi-tenant-auth/design.md

- Source: openspec/changes/multi-tenant-auth/design.md
- Lines: 1-267
- SHA256: 91ab3884cf7e442dde75d4c7ae372eff5a85017030d5ae54c6ad275f300adb48

[TRUNCATED]

```md
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

### ADR-4：跨租户 kb_id 拒绝策略

检索接口收到其他租户的 kb_id 时，返回 `FORBIDDEN (10201)` 而非 `NOT_FOUND (10300)`。

理由：KB 存在但不属于你，返回 NOT_FOUND 会误导调用方反复重试。FORBIDDEN 明确告知"这不是你的数据"。

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
        # 校验 Bearer → SHA-256 → 查 DB → TenantContext
        ...
    return get_current_tenant
```

`composition.py` 在 lifespan 中创建 repo 后调用一次：

```python
get_current_tenant_dep = make_get_current_tenant(
    tenant_repo, api_key_repo, settings.AUTH_ENABLED
)
```

Router 工厂函数接收 `get_current_tenant` 作为参数（与接收 UseCase 模式相同）：

```

Full source: openspec/changes/multi-tenant-auth/design.md

## openspec/changes/multi-tenant-auth/tasks.md

- Source: openspec/changes/multi-tenant-auth/tasks.md
- Lines: 1-38
- SHA256: 18b7f29e823f67771951821ce6944a3dd45d05d4353346dc33a620a0d713c160

```md
# Tasks: 多租户鉴权

> 设计：[design.md](./design.md)
> 提案：[proposal.md](./proposal.md)

## Phase 1: 后端鉴权地基

- [ ] 1.1 创建 Alembic 迁移 0003：`tenants` 表 + `api_keys` 表（字段、约束、索引）
- [ ] 1.2 迁移存量数据：扫描 `SELECT DISTINCT tenant_id FROM knowledge_bases`，对不在 tenants 中的逐条 `INSERT INTO tenants`；加 FK 约束 `knowledge_bases.tenant_id → tenants.id ON DELETE RESTRICT`
- [ ] 1.3 领域模型：`domain/models.py` 新增 `Tenant`、`ApiKey` dataclass
- [ ] 1.4 仓库层：`adapters/tenant/pg.py` 实现 `PgTenantRepository`（create/get/list）和 `PgApiKeyRepository`（create_by_hash/verify_hash）
- [ ] 1.5 鉴权核心：`core/auth.py` 实现 `TenantContext`、`make_get_current_tenant` 工厂函数（闭包注入 repo+config）、SHA-256 hash/verify、AUTH_ENABLED 占位逻辑
- [ ] 1.6 HTTP Depends：`adapters/http/deps.py` 重新导出 `make_get_current_tenant`
- [ ] 1.7 auth/me 端点：`adapters/http/auth_router.py` 实现 `GET /v1/auth/me`，返回当前 Key 的租户信息
- [ ] 1.8 配置：`config.py` 新增 `AUTH_ENABLED: bool = True`，`.env.example` 补充
- [ ] 1.9 运维脚本：`scripts/create_tenant.py`（`--id --name`，重复报错）
- [ ] 1.10 运维脚本：`scripts/create_api_key.py`（`--tenant-id --name`，终端打印一次明文 `rk_live_<32hex>`，tenant 不存在报错）
- [ ] 1.11 composition.py：lifespan 中创建 TenantRepository/ApiKeyRepository → `make_get_current_tenant` → 传入 auth_router 及业务 router 工厂
- [ ] 1.12 测试：迁移 up/down 测试 + `get_current_tenant` 单元测试（正常/无Key/错误Key/过期/禁用/AUTH_ENABLED=false 降级）

## Phase 2: 业务接口鉴权接入

- [ ] 2.1 `POST /v1/knowledge-bases:create`：`_CreateKBRequest` 移除 `tenant_id`（`extra="ignore"`），路由工厂加 `get_current_tenant` 参数，`tenant_id` 从 Key 注入
- [ ] 2.2 `GET /v1/knowledge-bases/tree`：UseCase 签名加 `tenant_id` 参数，keyword 语义改为「按 KB 名称模糊搜」，repo 查询改为 `WHERE kb.tenant_id = $1 AND kb.name ILIKE $2`，路由工厂加 `get_current_tenant` 参数
- [ ] 2.3 `POST /v1/documents:upload`：确认为 no-op（本来就不传 tenant_id），路由工厂加 `get_current_tenant` 参数（为后续扩展预留），当前不做归属校验
- [ ] 2.4 `POST /v1/rag:retrieve`：路由工厂加 `get_current_tenant` 参数；在 `RetrieveUseCase` 中新增 `validate_kb_ownership(kb_ids, tenant_id)` 方法（实现：`SELECT id FROM knowledge_bases WHERE id = ANY($kb_ids) AND tenant_id = $tenant_id` 对比数量），跨租户 kb_id → `FORBIDDEN (10201)`
- [ ] 2.5 测试：create KB 鉴权集成测试 + tree 按租户过滤测试 + retrieve 跨租户 kb_id 拒绝测试

## Phase 3: 前端适配

- [ ] 3.1 `http.ts` 拦截器：请求拦截器读取 `import.meta.env.API_KEY` 自动设置 `Authorization: Bearer`；响应拦截器检查 `code === 10200` 弹出错误提示（API Key 无效或未配置，请检查 admin/.env 中的 API_KEY）
- [ ] 3.2 环境变量：`admin/.env.example` 含 `VITE_API_BASE_URL` + `API_KEY`，`vite.config.ts` 加 `envPrefix: ['VITE_', 'API_']`，`vite-env.d.ts` 补充 `ImportMetaEnv`
- [ ] 3.3 类型定义：`types/api.ts` 三个 Request 类型移除 `tenant_id`，新增 `AuthMeData` 接口
- [ ] 3.4 服务层：`services/api.ts` 修改 createKB/uploadDoc/retrieve/fetchTree 的 payload 不传 `tenant_id`；新增 `services/authService.ts` 提供 `fetchAuthMe()`
- [ ] 3.5 上传页：创建 KB 表单去掉 tenant_id 输入（只留 name/description），上传表单去掉 tenant_id（只留 kb_id+文件），tenant_id 改为 Badge 只读展示
- [ ] 3.6 列表页：三级树→两级（flatMap 去重），标题右侧展示当前租户 name/id Badge（调 /auth/me），搜索改为按 KB 名称模糊搜，跳转 URL 只带 kb_id
- [ ] 3.7 检索页：去掉租户下拉筛选（只留 kb_id 选择），`buildRetrievePayload` 不传 tenant_id，检索参数标签旁新增 HelpTooltip 公共组件
- [ ] 3.8 测试：拦截器 10200 错误提示测试 + 上传页无 tenant_id 输入框测试 + 列表页两级渲染测试 + 检索页 HelpTooltip 渲染测试
```

