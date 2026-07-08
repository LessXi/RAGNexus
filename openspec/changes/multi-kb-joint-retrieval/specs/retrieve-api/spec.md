## MODIFIED Requirements

### Requirement: POST /v1/rag:retrieve 请求新增 query_options

The system SHALL implement this requirement.

请求体新增可选字段 `query_options`：

```json
{
  "query_options": {
    "enabled": true,
    "strategy": "rewrite"
  }
}
```

- `enabled: bool` — 是否启用 query 处理（改写 + 词表扩展）
- `strategy: str` — 改写策略（当前仅 `"rewrite"`）。`enabled=false` 时忽略

#### Scenario: 传 query_options.enabled=true
- **WHEN** 请求包含 `query_options: { enabled: true, strategy: "rewrite" }`
- **THEN** 后端执行 LLM 改写 + 词表扩展（若 KB 配置了 synonyms）
- **AND** 响应 `meta.query_processing` 包含完整链路

#### Scenario: 不传 query_options
- **WHEN** 请求不包含 `query_options`
- **THEN** 行为与改前完全一致
- **AND** 响应 `meta.query_processing` 为 `null`

#### Scenario: enabled=false, strategy="rewrite"
- **WHEN** `query_options: { enabled: false, strategy: "rewrite" }`
- **THEN** `enabled` 优先，不执行任何处理
- **AND** `query_processing` 为 `null`

### Requirement: 响应新增 data.query

The system SHALL implement this requirement.

`data.query` 字段返回用户原始输入，始终不被改写后的句子替换。

#### Scenario: 开启改写时 data.query 不变
- **GIVEN** `query_options.enabled=true`
- **WHEN** 请求 `query="背调要问啥"`
- **THEN** 响应 `data.query` = "背调要问啥"
- **AND** `meta.query_processing.effective_query` 可能不同

#### Scenario: 不传 query_options 时 data.query 仍存在
- **WHEN** 请求不包含 `query_options`
- **THEN** `data.query` = 请求中的 query（新增字段，始终返回）

### Requirement: 响应 meta 新增 query_processing

The system SHALL implement this requirement.

响应 `meta` 新增可选字段 `query_processing`，类型为 `QueryProcessResult` 的 JSON 序列化。

#### Scenario: query_processing 在 meta 中返回
- **WHEN** 请求启用 query_options
- **THEN** 响应 `meta.query_processing` SHALL 包含 rewritten、synonyms_applied 等链路信息

#### Scenario: 不传 query_options 时返回 null
- **WHEN** 请求不包含 query_options
- **THEN** `meta.query_processing` SHALL 为 null
### Requirement: 请求新增 profile 参数

检索请求体 SHALL 新增可选字段 `profile`，取值 speed / balanced / quality / custom。未传时默认 `balanced`。

#### Scenario: 传 profile=speed 时生效
- **WHEN** 请求包含 profile="speed"
- **THEN** 系统 SHALL 按 speed 预设配置检索参数

### Requirement: 响应 meta 新增 tenant_policy

响应 `meta` SHALL 新增可选字段 `tenant_policy`，描述本次检索生效的策略参数。

#### Scenario: tenant_policy 反映当前 plan 限制
- **WHEN** free 租户发起检索
- **THEN** `meta.tenant_policy` SHALL 包含 plan 对应的速率和配额限制

### Requirement: 错误码 API_RATE_LIMIT 变更为 20005

`ErrorCode.API_RATE_LIMIT` 的业务错误码 SHALL 从 20002 改为 20005。HTTP 状态码 429 保持不变。

#### Scenario: 触发限流返回 20005
- **WHEN** 租户超出 QPS 限制
- **THEN** 系统 SHALL 返回 code=20005, HTTP 429

### Requirement: 新增错误码 FEATURE_NOT_ALLOWED (20013)

系统 SHALL 支持错误码 `FEATURE_NOT_ALLOWED` (20013, HTTP 403)，在 plan 不允许请求的 profile、options 或多库检索上限时返回。

#### Scenario: profile 超 plan 返回 20013
- **WHEN** free 租户传 profile=balanced
- **THEN** 系统 SHALL 返回 code=20013, HTTP 403

#### Scenario: 多库超 plan 上限返回 20013
- **WHEN** free 租户传 kb_ids 长度 > plan.max_kb_per_retrieve
- **THEN** 系统 SHALL 返回 code=20013，提示当前套餐最多支持 N 个库联合检索

### Requirement: 新增错误码 QUOTA_EXCEEDED (20014)

系统 SHALL 支持错误码 `QUOTA_EXCEEDED` (20014, HTTP 429)，在租户超出配额上限时返回。

#### Scenario: 超配额返回 20014
- **WHEN** 租户超出知识库或文档数量配额
- **THEN** 系统 SHALL 返回 code=20014, HTTP 429

## ADDED Requirements

### Requirement: 响应 data 新增 kb_ids 字段

`POST /v1/rag:retrieve` 响应的 `data` 根级别 SHALL 新增 `kb_ids` 字段，返回本次检索实际查询的知识库 ID 列表。

```json
{
  "code": 0,
  "data": {
    "query": "...",
    "kb_ids": ["kb_ecommerce", "kb_customer_service"],
    "hits": [...]
  }
}
```

#### Scenario: 双库检索响应含 kb_ids

- **WHEN** 请求传入 `kb_ids: ["kb_ecommerce", "kb_customer_service"]`
- **THEN** 响应 `data.kb_ids` SHALL 为 `["kb_ecommerce", "kb_customer_service"]`

#### Scenario: 单库检索响应仍含 kb_ids

- **WHEN** 请求传入 `kb_ids: ["kb_single"]`
- **THEN** 响应 `data.kb_ids` SHALL 为 `["kb_single"]`

### Requirement: 响应 meta 新增多库融合元信息

响应 `meta` SHALL 新增以下多库检索元信息字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `multi_kb` | `bool` | 是否为多库检索 |
| `kb_count` | `int` | 联查库数量 |
| `per_kb_top_k` | `int` | 每库召回候选数 |
| `fusion` | `str` | 融合方式（`"rrf"`） |
| `rrf_k` | `int` | RRF 参数 |

#### Scenario: 多库检索 meta 含完整多库信息

- **WHEN** 双库检索成功
- **THEN** `meta.multi_kb` SHALL 为 true
- **AND** `meta.kb_count` SHALL 为 2
- **AND** `meta.fusion` SHALL 为 "rrf"

#### Scenario: 单库检索 meta 多库字段为 false

- **WHEN** 单库检索
- **THEN** `meta.multi_kb` SHALL 为 false
- **AND** 其他多库字段可选存在

### Requirement: chunk 响应新增 kb_name

每条 `hits[*]` SHALL 新增 `kb_name` 字段，为知识库名称（或 `kb_id` 前 8 位作为回退）。

#### Scenario: chunk 带 kb_name

- **GIVEN** kb_ecommerce 的库名为 "电商规则库"
- **WHEN** 检索返回该库的 chunk
- **THEN** 该 chunk 的 `kb_name` SHALL 为 "电商规则库"
