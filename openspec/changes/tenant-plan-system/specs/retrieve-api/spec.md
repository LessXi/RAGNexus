## ADDED Requirements

### Requirement: 请求新增 profile 参数

检索请求体 SHALL 新增可选字段 `profile`，取值 speed / balanced / quality / custom。未传时默认 `balanced`。

```json
{
  "profile": "balanced",
  "query": "...",
  "kb_ids": [...]
}
```

#### Scenario: 传 profile=speed
- **WHEN** 请求包含 `profile: "speed"`
- **THEN** 系统 SHALL 按 speed 预设展开检索参数（mode=vector, top_k=3, 关闭 rerank 和 rewrite）

#### Scenario: 不传 profile 默认 balanced
- **WHEN** 请求未包含 `profile` 字段
- **THEN** 系统 SHALL 按 balanced 预设展开（mode=hybrid, top_k=5, 关闭 rerank 和 rewrite）
- **AND** 行为 SHALL 与改前一致（向后兼容）

#### Scenario: profile 不被 plan 允许
- **WHEN** free 租户传 `profile: "balanced"`
- **THEN** 系统 SHALL 返回 code=20013, 不执行检索

### Requirement: 响应 meta 新增 tenant_policy

响应 `meta` SHALL 新增可选字段 `tenant_policy`，描述本次检索生效的策略参数：

```json
{
  "meta": {
    "tenant_policy": {
      "plan": "pro",
      "retrieve_profile": "quality",
      "effective_mode": "hybrid",
      "effective_rerank": true,
      "effective_query_rewrite": true
    }
  }
}
```

#### Scenario: quality profile 返回完整 tenant_policy
- **WHEN** pro 租户传 profile=quality
- **THEN** meta.tenant_policy.plan SHALL 为 "pro"
- **AND** meta.tenant_policy.retrieve_profile SHALL 为 "quality"
- **AND** meta.tenant_policy.effective_rerank SHALL 为 true
- **AND** meta.tenant_policy.effective_query_rewrite SHALL 为 true

#### Scenario: speed profile 不启用高级功能
- **WHEN** 任意租户传 profile=speed
- **THEN** meta.tenant_policy.effective_rerank SHALL 为 false
- **AND** meta.tenant_policy.effective_query_rewrite SHALL 为 false

### Requirement: 错误码 API_RATE_LIMIT 变更为 20005

`ErrorCode.API_RATE_LIMIT` 的业务错误码 SHALL 从 20002 改为 20005。HTTP 状态码 429 保持不变。

#### Scenario: QPS 超限返回 20005
- **WHEN** 检索 QPS 超限
- **THEN** 系统 SHALL 返回 `"code": 20005`, HTTP 429

### Requirement: 新增错误码 FEATURE_NOT_ALLOWED (20013)

系统 SHALL 支持错误码 `FEATURE_NOT_ALLOWED` (20013, HTTP 403)，在 plan 不允许请求的 profile 或 options 时返回。

#### Scenario: profile 超 plan 返回 20013
- **WHEN** free 租户传 profile=balanced
- **THEN** 系统 SHALL 返回 `"code": 20013, message: "当前套餐 free 不支持检索预设 balanced"`, HTTP 403

### Requirement: 新增错误码 QUOTA_EXCEEDED (20014)

系统 SHALL 支持错误码 `QUOTA_EXCEEDED` (20014, HTTP 429)，在租户超出配额上限时返回。

#### Scenario: 建库超配额返回 20014
- **WHEN** free 租户尝试创建第二个知识库
- **THEN** 系统 SHALL 返回 `"code": 20014, message: "免费档仅支持 1 个知识库"`, HTTP 429
