---
comet_change: multi-tenant-auth
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-05-multi-tenant-auth
status: final
---

# 多租户鉴权 — 技术设计

> 关联 Proposal：[openspec/changes/multi-tenant-auth/proposal.md](../../openspec/changes/multi-tenant-auth/proposal.md)
> 关联 OpenSpec Design：[openspec/changes/multi-tenant-auth/design.md](../../openspec/changes/multi-tenant-auth/design.md)
> 融合分析：[docs/superpowers/analysis/2026-07-04-multi-tenant-auth-fusion.md](../analysis/2026-07-04-multi-tenant-auth-fusion.md)

## 概述

将 RAGNexus 从「客户端传 tenant_id、服务端无条件信任」改造为「API Key 鉴权、服务端派生租户身份」。后端新增 tenants/api_keys 表、auth 核心、/auth/me 端点，五个接口全部接入鉴权（含 upload/retrieve 跨租户资源拒绝）。前端新增请求拦截器自动带 Key，三个页面移除 tenant_id 输入。

## 架构决策

### ADR-1：API Key + Bearer Token 方案

- **Key 格式**：`rk_live_<32位hex>`，SHA-256 hash 存入 `api_keys.key_hash`
- **传递方式**：`Authorization: Bearer rk_live_xxx`
- **校验入口**：FastAPI `Depends(get_current_tenant)` → `TenantContext`
- **降级开关**：`AUTH_ENABLED=false` 跳过验 Key，固定占位租户 `default`

### ADR-2：FK 约束 RESTRICT

`knowledge_bases.tenant_id` → `tenants.id` ON DELETE RESTRICT。有 KB 时禁删租户，防孤儿数据。

### ADR-3：错误码沿用 10200

沿用现有 `UNAUTHORIZED = (10200, 401)`，不动全局 error_handler。

### ADR-4：跨租户资源拒绝策略

upload/retrieve 接口收到其他租户的 kb_id 时，返回 `FORBIDDEN (10201)` 而非 `NOT_FOUND (10300)`。

理由：KB 存在但不属于你，返回 NOT_FOUND 会误导调用方反复重试。FORBIDDEN 明确告知「这不是你的数据」。upload（`UploadDocumentUseCase` 入口校验 `kb.tenant_id != tenant_id`）和 retrieve（`RetrieveUseCase.validate_kb_ownership`，`set(kb_ids)` 去重后 COUNT 对比）共享同一策略。

### ADR-5：前端 API_KEY 暴露本期接受

Vite 打包会内联 `import.meta.env.API_KEY` 到 JS bundle。对内网管理 SPA 可接受，标注风险。下期独立 change 做 session token。

### ADR-6：Depends 依赖注入 — 工厂函数闭包

```python
# core/auth.py
def make_get_current_tenant(tenant_repo, api_key_repo, auth_enabled):
    async def get_current_tenant(
        authorization: str | None = Header(None),
    ) -> TenantContext:
        if not auth_enabled: return TenantContext(...)
        if authorization is None: raise AppError(UNAUTHORIZED, "缺少 Authorization 请求头")
        # extract Bearer → SHA-256 → DB JOIN → validate → TenantContext
    return get_current_tenant

# composition.py — 所有 5 个 Router 工厂统一加 get_current_tenant 参数
get_current_tenant_dep = make_get_current_tenant(tenant_repo, api_key_repo, settings.AUTH_ENABLED)
app.include_router(create_auth_router(get_current_tenant_dep))
app.include_router(create_kb_router(uc, get_current_tenant_dep))
app.include_router(create_kb_tree_router(uc, get_current_tenant_dep))
app.include_router(create_upload_doc_router(uc, get_current_tenant_dep))
app.include_router(create_retrieve_router(uc, get_current_tenant_dep))
```

## 数据模型

```
tenants: id(TEXT PK), name, status(active/disabled), created_at
api_keys: id(UUID PK), tenant_id(FK→tenants), key_hash(TEXT UNIQUE), key_prefix, name, status(active/revoked), expires_at?, created_at
  索引：idx_api_keys_tenant ON (tenant_id)
knowledge_bases.tenant_id: FK→tenants.id ON DELETE RESTRICT
```

### TenantContext

```python
@dataclass
class TenantContext:
    tenant_id: str    # 鉴权通过后的租户 ID
    tenant_name: str  # 租户展示名
    key_id: str       # api_keys.id (UUID)
    key_prefix: str   # "rk_a1b2"，日志辨认用
```

### key_prefix 规则

`"rk_" + secrets.token_hex(16) 的前 4 个字符` → `"rk_a1b2"`。不含 `live_` 部分。

### AUTH_ENABLED=false 降级

`tenant_id="default"`, `tenant_name="默认租户"`（硬编码，不查 DB）。

## 业务接口变更

| 接口 | 变更 | BREAKING？ |
|---|---|---|
| `POST /v1/knowledge-bases:create` | 移除 body `tenant_id`，Key 注入 | **是** |
| `GET /v1/knowledge-bases/tree` | 单租户数组，keyword 按 KB 名搜 | **是** |
| `POST /v1/documents:upload` | 新增 kb_id 归属校验 → FORBIDDEN | **是** |
| `POST /v1/rag:retrieve` | 新增 kb_ids 归属校验 → FORBIDDEN | **是** |

## 新增组件

| 文件 | 职责 |
|---|---|
| `core/auth.py` | TenantContext + make_get_current_tenant + SHA-256 hash/extract 纯函数 |
| `adapters/tenant/pg.py` | PgTenantRepository + PgApiKeyRepository |
| `adapters/http/auth_router.py` | GET /v1/auth/me |
| `adapters/http/deps.py` | 重新导出 make_get_current_tenant |
| `scripts/create_tenant.py` | 注册租户 |
| `scripts/create_api_key.py` | 给租户发 Key |
| Alembic 0003 | 建表 + 存量迁移 + FK + 索引 |

## 前端变更

| 文件 | 变更 |
|---|---|
| `admin/src/lib/axios.ts` | 请求拦截器 Bearer + 响应/错误双拦截器 10200 处理 |
| `admin/src/types/api.ts` | Request 去 tenant_id + 新增 AuthMeData |
| `admin/src/services/authService.ts` | fetchAuthMe() |
| `admin/src/pages/upload-doc.tsx` | 去 tenant_id 输入 |
| `admin/src/pages/knowledge-file-tree.tsx` | 三级→两级 + 租户 badge |
| `admin/src/pages/retrieve.tsx` | 去租户筛选 + HelpTooltip |

## 存量数据迁移

迁移 0003 自动处理：① 建 tenants 表 ② INSERT tenants(id='default') ③ 扫描 `DISTINCT tenant_id FROM knowledge_bases WHERE tenant_id IS NOT NULL AND tenant_id != ''` 补录 ④ 建 api_keys 表 + idx_api_keys_tenant 索引 ⑤ 加 FK RESTRICT。降级：DROP FK → DROP TABLE。

## 测试策略

- **Phase 1**：迁移 up/down + `get_current_tenant` 单元（正常/Header缺失/错误Key/过期Key/已吊销Key/租户禁用/降级）
- **Phase 2**：create KB 鉴权集成 + tree 租户过滤 + upload 跨租户拒绝 + retrieve 跨租户拒绝（含重复 kb_id 去重场景）
- **Phase 3**：拦截器双路径 10200 提示 + 上传页无 tenant_id 输入 + 列表页两级渲染 + HelpTooltip 渲染
