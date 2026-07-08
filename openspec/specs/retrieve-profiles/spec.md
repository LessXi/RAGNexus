# retrieve-profiles Specification

## Purpose
TBD - created by archiving change tenant-plan-system. Update Purpose after archive.
## Requirements
### Requirement: 四档检索预设定义

系统 SHALL 支持四档检索预设（speed / balanced / quality / custom），定义在 `retrieve_presets.py` 常量中。

- **speed**: mode=vector, top_k=3, 关 rerank 和 rewrite
- **balanced**: mode=hybrid, top_k=5, 关 rerank 和 rewrite（默认）
- **quality**: mode=hybrid, top_k=8, 开 rerank(take=5) 和 rewrite
- **custom**: 不展开默认值，使用请求中显式传入的 options

#### Scenario: 未传 profile 默认 balanced
- **WHEN** 检索请求未包含 `profile` 字段
- **THEN** 系统 SHALL 按 balanced 预设展开，mode=hybrid, top_k=5, rerank 和 rewrite 关闭

#### Scenario: speed 预设展开
- **WHEN** profile=speed
- **THEN** 系统 SHALL 展开为 mode=vector, top_k=3, rerank_enabled=false, query_options={"enabled":false}

#### Scenario: quality 预设展开
- **WHEN** profile=quality
- **THEN** 系统 SHALL 展开为 mode=hybrid, top_k=8, rerank_enabled=true, rerank_top_n=5, query_options={"enabled":true,"strategy":"rewrite"}

### Requirement: Profile 与 Plan 的校验

系统 SHALL 按 plan 校验 profile：profile 不在 plan.features.allowed_profiles 列表时 MUST 返回 20013。

- free: ["speed"]
- standard: ["speed", "balanced", "custom"]
- pro: ["speed", "balanced", "quality", "custom"]

#### Scenario: free 请求 balanced 被拒绝
- **WHEN** free 租户传 profile=balanced
- **THEN** 系统 SHALL 返回 code=20013, message 含 "当前套餐 free 不支持检索预设 balanced"

#### Scenario: standard 请求 quality 被拒绝
- **WHEN** standard 租户传 profile=quality
- **THEN** 系统 SHALL 返回 code=20013

#### Scenario: pro 请求 quality 成功
- **WHEN** pro 租户传 profile=quality
- **THEN** 系统 SHALL 成功执行，metadata.tenant_policy.retrieve_profile 为 quality, effective_rerank 为 true

### Requirement: Custom profile 受 plan 约束

当 profile=custom 时，系统 SHALL 使用请求中显式传入的 options，但仍 MUST 校验各选项不超过 plan.features 上限。

#### Scenario: standard + custom + rerank 被拒绝
- **WHEN** standard 租户传 profile=custom 且 rerank_options.enabled=true
- **THEN** 系统 SHALL 返回 code=20013，因为 standard 不允许 rerank

#### Scenario: free + custom + hybrid 被拒绝
- **WHEN** free 租户传 profile=custom 且 mode=hybrid
- **THEN** 系统 SHALL 返回 code=20013，因为 free 不允许 hybrid

### Requirement: Plan ceiling 优先于 .env 全局开关

Profile 展开后的参数 MUST 覆盖（而非叠加）uc.execute() 的参数。即使 `.env` 中 `RERANK_ENABLED=true`，free 租户的 balanced profile 展开后 rerank_enabled=false MUST 生效。

#### Scenario: .env RERANK_ENABLED=true 但 free balanced 不 rerank
- **WHEN** `.env` 设 `RERANK_ENABLED=true` 且 free 租户传 profile=balanced
- **THEN** 传给 `uc.execute()` 的 rerank_enabled SHALL 为 false

