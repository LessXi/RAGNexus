---
change: multi-tenant-auth
design-doc: docs/superpowers/specs/2026-07-04-multi-tenant-auth-design.md
base-ref: 3c5665b60661f526d10d35a3457c925e43cb7912
archived-with: 2026-07-05-multi-tenant-auth
---

# 多租户鉴权 — 实施计划

> 关联 Design Doc：[docs/superpowers/specs/2026-07-04-multi-tenant-auth-design.md](../specs/2026-07-04-multi-tenant-auth-design.md)
> 关联 Tasks：[openspec/changes/multi-tenant-auth/tasks.md](../../openspec/changes/multi-tenant-auth/tasks.md)

## 概述

三阶段串行执行（Phase 1→2 后端有强依赖，Phase 3 可部分并行）。共 27 个任务，约 800-1200 行净增代码。

## Phase 1：后端鉴权地基（13 任务）

建立 tenants/api_keys 表、auth 核心、运维脚本，/auth/me 端点独立可用。此阶段完成后即可用 curl 验证鉴权流程。

| # | 任务 | 文件 | 类型 | 预估行数 |
|---|---|---|---|---|
| 1.1 | Alembic 0003 迁移 | `alembic/versions/0003_*.py` | 新建 | ~80 |
| 1.2 | 存量数据迁移 + FK | 同上 | 修改 | ~20 |
| 1.3 | Tenant/ApiKey dataclass | `src/ragnexus/domain/models.py` | 修改 | ~30 |
| 1.4 | Tenant/ApiKey Repository | `src/ragnexus/adapters/tenant/pg.py` | 新建 | ~80 |
| 1.5a | TenantContext + 纯函数 | `src/ragnexus/core/auth.py` | 新建 | ~40 |
| 1.5b | make_get_current_tenant Depends | 同上 | 修改 | ~60 |
| 1.6 | deps.py 重新导出 | `src/ragnexus/adapters/http/deps.py` | 新建 | ~5 |
| 1.7 | /auth/me 端点 | `src/ragnexus/adapters/http/auth_router.py` | 新建 | ~40 |
| 1.8 | AUTH_ENABLED 配置 | `src/ragnexus/config.py` + `.env.example` | 修改 | ~5 |
| 1.9 | create_tenant.py | `scripts/create_tenant.py` | 新建 | ~50 |
| 1.10 | create_api_key.py | `scripts/create_api_key.py` | 新建 | ~60 |
| 1.11 | composition.py DI 装配 | `src/ragnexus/composition.py` | 修改 | ~30 |
| 1.12 | 迁移 + auth 单元测试 | `tests/unit/test_auth.py` | 新建 | ~150 |

## Phase 2：业务接口鉴权接入（5 任务）

四个业务接口全部接入 Depends(get_current_tenant)，upload 和 retrieve 新增跨租户校验。

| # | 任务 | 文件 | 类型 | 预估行数 |
|---|---|---|---|---|
| 2.1 | create KB 去 tenant_id | `create_kb_router.py` + `create_kb_use_case.py` | 修改 | ~15 |
| 2.2 | tree 按租户过滤 | `kb_tree_router.py` + `kb_tree_use_case.py` + `adapters/knowledge_base/pg.py` | 修改 | ~30 |
| 2.3 | upload 归属校验 | `upload_doc_router.py` + `upload_doc_use_case.py` | 修改 | ~15 |
| 2.4 | retrieve 归属校验 | `retrieve_router.py` + `retrieve_use_case.py` | 修改 | ~25 |
| 2.5 | 业务集成测试 | `tests/integration/test_auth_*.py` | 新建 | ~120 |

## Phase 3：前端适配（9 任务）

前端去除所有 tenant_id 输入，列表页三级→两级，新增拦截器和帮助组件。

| # | 任务 | 文件 | 类型 | 预估行数 |
|---|---|---|---|---|
| 3.1 | axios 双拦截器 | `admin/src/lib/axios.ts` | 修改 | ~30 |
| 3.2 | 环境变量 + envPrefix + .gitignore | `admin/.env.example` + `vite.config.ts` + `vite-env.d.ts` | 修改/新建 | ~15 |
| 3.3 | 类型定义去 tenant_id | `admin/src/types/api.ts` | 修改 | ~10 |
| 3.4 | 服务层去 tenant_id + authService | `admin/src/services/api.ts` + `authService.ts` | 修改/新建 | ~25 |
| 3.5 | 上传页去 tenant_id | `admin/src/pages/upload-doc.tsx` | 修改 | ~20 |
| 3.6 | 列表页三级→两级 | `admin/src/pages/knowledge-file-tree.tsx` | 修改 | ~30 |
| 3.7 | 检索页去 tenant_id + HelpTooltip | `admin/src/pages/retrieve.tsx` | 修改 | ~30 |
| 3.8 | 前端测试 | `admin/src/__tests__/` | 新建/修改 | ~100 |
| 3.9 | README 更新 | `README.md` | 修改 | ~15 |

## 执行顺序

```
Phase 1:
  1.1 ─→ 1.2 ─→ 1.4 ─→ 1.5a ─→ 1.5b ─→ 1.6 ─→ 1.7 ─→ 1.8 ─→ 1.9 ─→ 1.10 ─→ 1.11 ─→ 1.12
        1.3 ──────────────────────────────────────────────┘（可与 1.1 并行）
                                    ↓
Phase 2:
  2.1 ─→ 2.2 ─→ 2.3 ─→ 2.4 ─→ 2.5
  2.1/2.2/2.3/2.4 彼此独立（改不同接口），可并行执行
                                    ↓
Phase 3:
  3.1 ─→ 3.2 ─→ 3.3 ─→ 3.4 ─┐
                              ├─→ 3.5 ┐
                              │       ├─→ 3.8 ─→ 3.9
                              │  3.6 ┤（页面独立，可并行）
                              │  3.7 ┘
```

Phase 1 内 1.3（领域模型）与 1.1（迁移建表）可并行。Phase 2 四个接口互不依赖可全并行。Phase 3 中 3.5/3.6/3.7 三个页面改造彼此独立可并行，3.3+3.4 也可并行。

## 风险

| 风险 | 缓解 |
|---|---|
| 存量数据 tenant_id 不匹配 | 迁移 1.2 自动扫描 DISTINCT tenant_id 并补录 tenants 表 |
| Router 工厂签名变更遗漏某个 Router | 1.11 一次性改完 composition.py 所有 5 个工厂调用，2.5 集成测试覆盖全部接口 |
| 迁移降级失败（FK 约束阻挡 DOWN） | design.md 已定义降级策略：先 DROP FK 再 DROP TABLE，1.12 测试覆盖 up/down |
| 前端 API_KEY 打包暴露到 JS bundle | design.md ADR-5 标记为已知限制（内网 SPA 可接受），README 3.9 注明风险 |
| 前端 10200 拦截器双路径遗漏 | 3.8 测试覆盖 response + error 两个拦截器路径 |
