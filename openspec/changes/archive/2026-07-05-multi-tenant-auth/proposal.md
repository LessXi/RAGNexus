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
- `POST /v1/documents:upload` 新增 kb_id 归属校验，跨租户上传 → `FORBIDDEN (10201)`
- `POST /v1/rag:retrieve` 新增 kb_ids 归属校验，跨租户 kb_id → `FORBIDDEN (10201)`

### 前端 — Phase 3：去 tenant_id 适配

- `http.ts` 新增请求/响应拦截器：自动带 Bearer Key、拦截 code 10200 错误提示
- 三个页面移除 `tenant_id` 输入/筛选，列表页三级树改为两级 + 租户 badge
- types/services 新增 `authService.ts`/`AuthMeData`，Request 类型移除 `tenant_id`
- 新增 `admin/.env.example` 含 `API_KEY`，vite.config.ts 加 `envPrefix`

## Capabilities

### New Capabilities

- `multi-tenant-auth-backend`: 租户管理（tenants/api_keys 表、模型、仓库、运维脚本）、API Key 鉴权（生成/校验/SHA-256 存储）、FastAPI Depends 注入、AUTH_ENABLED 开关、/auth/me 验证端点
- `multi-tenant-auth-frontend`: 请求拦截器自动带 Key、响应拦截 10200 错误提示、三级树→两级树 UI、租户 badge、HelpTooltip 组件

### Modified Capabilities

- `knowledge-base-crud`: create 请求体移除 tenant_id，tree 按租户过滤
- `rag-retrieval`: 新增 kb_ids 租户归属校验
