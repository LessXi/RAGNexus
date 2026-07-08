# retrieve-api (delta)

retrieve API 变更：请求新增 `query_options`，响应新增 `data.query` 和 `meta.query_processing`。

## ADDED Requirements

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

响应 `meta` 新增可选字段 `query_processing`，类型为 `QueryProcessResult` 的 JSON 序列化：

```json
{
  "raw_query": "...",
  "effective_query": "...",
  "search_query": "...",
  "needs_rewrite": true,
  "strategy": "rewrite",
  "rewrite_latency_ms": 480,
  "degraded": false,
  "degraded_reason": null,
  "synonym_applied": true,
  "synonym_expansions": ["背景调查", "标准问题清单"]
}
```

#### Scenario: 有处理时返回完整链路
- **GIVEN** 开了改写且词表命中
- **THEN** `meta.query_processing` 包含上述所有字段

#### Scenario: 仅改写无词表
- **GIVEN** 开了改写但 KB 无 synonyms
- **THEN** `synonym_applied` = false, `synonym_expansions` = []
- **AND** `search_query` = `effective_query`

#### Scenario: 无处理时返回 null
- **GIVEN** 未传 `query_options` 且 KB 无 settings
- **THEN** `meta.query_processing` 为 `null`
