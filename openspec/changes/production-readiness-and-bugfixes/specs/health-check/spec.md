## ADDED Requirements

### Requirement: 健康检查端点

系统 SHALL 提供一个 GET /health 端点，用于负载均衡和容器编排的存活探针。

#### Scenario: 正常响应
- **WHEN** 数据库连接池可达且 Embedder API 端点可响应
- **THEN** 返回 HTTP 200 状态码，JSON body 包含 `{"status": "ok", "timestamp": "<ISO8601>", "checks": {"database": "ok", "embedder": "ok"}}`

#### Scenario: 数据库不可达
- **WHEN** 数据库连接池 acquire 超时或返回连接错误
- **THEN** 返回 HTTP 503 状态码，JSON body 包含 `{"status": "degraded", "checks": {"database": "error", "embedder": "<实际状态>"}}`

#### Scenario: Embedder API 不可达
- **WHEN** Embedder API 端点连接超时或返回非 2xx
- **THEN** 返回 HTTP 503 状态码，JSON body 包含 `{"status": "degraded", "checks": {"database": "ok", "embedder": "error"}}`

#### Scenario: 超时保护
- **WHEN** 任一健康检查单项超过 3 秒未返回
- **THEN** 该单项标记为 "timeout"，不阻塞整体响应

### Requirement: 系统元信息披露

健康检查端点 SHALL 同时暴露最小系统元信息，便于运维快速诊断。

#### Scenario: 基本信息
- **WHEN** 请求 GET /health
- **THEN** 响应中包含 `"version": "<pyproject.toml version>"`、`"uptime_seconds": <进程启动到现在的秒数>`、`"python_version": "<sys.version>"`

## REMOVED Requirements

<!-- 无 -->
