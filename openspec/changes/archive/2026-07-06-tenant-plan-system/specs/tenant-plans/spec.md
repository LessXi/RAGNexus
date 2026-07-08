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
