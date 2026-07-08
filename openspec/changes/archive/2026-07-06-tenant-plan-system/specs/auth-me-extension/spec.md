## ADDED Requirements

### Requirement: /auth/me 返回 plan 字段

`GET /v1/auth/me` SHALL 在响应 data 中返回 `plan` 字段，值为 free / standard / pro。

#### Scenario: standard 租户查询身份
- **WHEN** standard 租户的 API Key 请求 /auth/me
- **THEN** 响应 data.plan SHALL 为 "standard"

### Requirement: /auth/me 返回 features 字段

`GET /v1/auth/me` SHALL 在响应 data 中返回 `features` 对象，包含 allowed_profiles、hybrid_allowed、rerank_allowed、query_rewrite_allowed。

#### Scenario: standard 租户 features
- **WHEN** standard 租户请求 /auth/me
- **THEN** data.features.allowed_profiles SHALL 为 ["speed", "balanced", "custom"]，data.features.rerank_allowed SHALL 为 false

### Requirement: /auth/me 返回 limits 字段

`GET /v1/auth/me` SHALL 在响应 data 中返回 `limits` 对象，包含 retrieve_qps、retrieve_daily、max_kb、max_documents_per_kb、max_processing_documents。

#### Scenario: standard 租户 limits
- **WHEN** standard 租户请求 /auth/me
- **THEN** data.limits.retrieve_qps SHALL 为 10，data.limits.max_kb SHALL 为 5，data.limits.retrieve_daily SHALL 为 5000

### Requirement: /auth/me 返回 usage 字段

`GET /v1/auth/me` SHALL 在响应 data 中返回 `usage` 对象，包含 kb_count（从 DB 实时查询）和 retrieve_daily_count（从 Redis 实时查询）。

#### Scenario: usage 实时反映当前用量
- **WHEN** standard 租户请求 /auth/me
- **THEN** data.usage.kb_count SHALL 等于该租户下知识库的实际数量；data.usage.retrieve_daily_count SHALL 等于 Redis 中日检索计数器的当前值
