## ADDED Requirements

### Requirement: E2E 测试使用 pytest-httpx 确定性 mock

系统 SHALL E2E 测试使用 pytest-httpx 确定性 mock。

E2E 测试通过 pytest-httpx mock 外部 HTTP 调用，确保确定性、可进 CI。

#### Scenario: embedder 请求被 mock 拦截
- **WHEN** E2E 测试发起上传请求
- **THEN** 所有发往 EMBED_BASE_URL 的 HTTP 请求被 pytest-httpx mock 拦截
- **AND** mock 返回预定义的向量

#### Scenario: LLM 请求被 mock 拦截
- **WHEN** E2E 测试启用 rerank/rewrite
- **THEN** 所有发往 LLM_BASE_URL 的 HTTP 请求被 pytest-httpx mock 拦截
- **AND** mock 返回预定义的 JSON 响应

### Requirement: /health 端点 E2E 测试

系统 SHALL /health 端点 E2E 测试。

#### Scenario: 正常响应
- **WHEN** GET /health 且数据库可连接
- **THEN** 返回 200
- **AND** body 含 {"status": "ok", "checks": {"database": "ok"}}
- **AND** 含 version、timestamp、uptime_seconds、python_version 字段

#### Scenario: 数据库不可用时降级
- **WHEN** GET /health 且数据库连接超时
- **THEN** 返回 503
- **AND** body 含 {"status": "degraded", "checks": {"database": "error"}}

### Requirement: Rewrite 启用全流程 E2E

系统 SHALL Rewrite 启用全流程 E2E。

#### Scenario: 查询改写后检索
- **WHEN** rewrite 启用且发起 retrieve 请求
- **THEN** LLM 被调用进行查询改写
- **AND** 改写后的查询用于向量搜索

### Requirement: Rerank 启用全流程 E2E

系统 SHALL Rerank 启用全流程 E2E。

#### Scenario: 重排后结果排序改变
- **WHEN** rerank 启用且发起 retrieve 请求
- **THEN** LLM 被调用进行重排打分
- **AND** 返回结果按 rerank_score 降序排列

### Requirement: 并发请求 E2E

系统 SHALL 并发请求 E2E。

#### Scenario: 5 并发检索无错误
- **WHEN** 同时发起 5 个检索请求
- **THEN** 所有请求返回 200，无 500 错误
- **AND** 连接池未耗尽

### Requirement: 外部服务降级 E2E

系统 SHALL 外部服务降级 E2E。

#### Scenario: embedder 超时时优雅降级
- **WHEN** mock embedder 返回超时
- **THEN** 上传请求返回 5xx 错误而非 crash
- **AND** 应用仍可接受后续请求

#### Scenario: LLM 429 限流时优雅降级
- **WHEN** mock LLM 返回 429
- **THEN** 检索请求降级返回原始向量排序结果
- **AND** 不抛异常到 HTTP 层
