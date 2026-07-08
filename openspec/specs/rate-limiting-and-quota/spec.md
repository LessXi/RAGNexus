# rate-limiting-and-quota Specification

## Purpose
TBD - created by archiving change tenant-plan-system. Update Purpose after archive.
## Requirements
### Requirement: QPS 限流

系统 SHALL 通过 Redis 对检索请求执行基于租户的 QPS 限流。Redis key 格式为 `rag:ratelimit:retrieve:{tenant_id}:{unix_second}`，TTL 2 秒。

#### Scenario: QPS 未超限正常放行
- **WHEN** free 租户（QPS=3）在 1 秒内第 1-3 次检索
- **THEN** 请求 SHALL 正常放行

#### Scenario: QPS 超限拒绝
- **WHEN** free 租户（QPS=3）在 1 秒内第 4 次检索
- **THEN** 系统 SHALL 返回 code=20005, message 含 "检索 QPS 超限"

### Requirement: 日检索量配额

系统 SHALL 通过 Redis 跟踪每个租户的日检索量。Redis key 格式为 `rag:quota:retrieve:daily:{tenant_id}:{YYYYMMDD}`，TTL 25 小时。仅在检索成功后 +1，失败/被拒绝的不计数。

#### Scenario: 日配额未超继续检索
- **WHEN** free 租户（日上限 500）当日检索 500 次
- **THEN** 第 501 次请求 SHALL 返回 code=20014, message 含 "日检索量已达上限"

#### Scenario: 检索失败不计数
- **WHEN** 检索因 profile 校验返回 20013 或因 QPS 返回 20005
- **THEN** 日配额计数器 SHALL NOT 增长

### Requirement: 建库配额

系统 SHALL 在建库前检查租户下的知识库数不超过 plan.limits.max_kb。

#### Scenario: free 建第二个库被拒绝
- **WHEN** free 租户已有 1 个知识库，尝试再建一个
- **THEN** 系统 SHALL 返回 code=20014, message 含 "免费档仅支持 1 个知识库"

### Requirement: 上传配额

系统 SHALL 在上传文档前检查 (1) 单库文档数不超过 max_documents_per_kb，(2) 租户下 PROCESSING 状态的文档数不超过 max_processing_documents。

#### Scenario: 单库文档数超限
- **WHEN** free 租户在已有 30 个文档的库中再上传
- **THEN** 系统 SHALL 返回 code=20014

#### Scenario: 并发 PROCESSING 超限
- **WHEN** free 租户已有 1 个 PROCESSING 文档，再上传第二个
- **THEN** 系统 SHALL 返回 code=20014, message 含 "并发索引文档数已达上限"

### Requirement: Reindex 配额

系统 SHALL 在 reindex 前检查租户下 PROCESSING 状态的文档数不超过 max_processing_documents。

#### Scenario: reindex 超并发限制
- **WHEN** free 租户已有 1 个 PROCESSING 文档，对另一文档发起 reindex
- **THEN** 系统 SHALL 返回 code=20014

