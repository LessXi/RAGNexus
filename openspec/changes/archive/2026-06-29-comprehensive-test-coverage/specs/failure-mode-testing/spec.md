## ADDED Requirements

### Requirement: Embedder 超时降级

系统 SHALL Embedder 超时降级。

#### Scenario: embedder API 超时
- **WHEN** embedder.embed() 调用超时
- **THEN** 抛出明确的应用异常（非原始 httpx 异常）
- **AND** 异常含可操作的错误信息

#### Scenario: embedder 重试耗尽后失败
- **WHEN** embedder API 连续失败超过 max_retries
- **THEN** 抛出异常，最后一次失败原因被保留

### Requirement: LLM Provider 降级

系统 SHALL LLM Provider 降级。

#### Scenario: LLM API 返回 429
- **WHEN** LLM API 返回 HTTP 429
- **THEN** 调用方（rerank/rewrite）感知为失败
- **AND** rerank 降级返回原始向量排序
- **AND** rewrite 降级使用原始查询

#### Scenario: LLM API 连接拒绝
- **WHEN** LLM_BASE_URL 不可达
- **THEN** 连接异常被正确捕获并包装

### Requirement: 并发控制 Semaphore 验证

系统 SHALL 并发控制 Semaphore 验证。

#### Scenario: Semaphore 限制并发数
- **WHEN** 同时发起超过 max_concurrency 的 embedder 调用
- **THEN** 超出并发的调用等待而非立即失败
- **AND** Semaphore 正确释放（无泄漏）

#### Scenario: 并发未超限时全速执行
- **WHEN** 并发数不超过 max_concurrency
- **THEN** 所有调用不被 Semaphore 阻塞

### Requirement: 生命周期错误恢复

系统 SHALL 生命周期错误恢复。

#### Scenario: Store 连接失败时清理已创建资源
- **WHEN** PgVectorStore.connect() 失败
- **THEN** 已创建的 _raw_store_pool 被正确关闭
- **AND** 不泄漏连接

#### Scenario: Embedder 初始化后 Store 连接失败
- **WHEN** 流程已创建 embedder 但 store 连接失败
- **THEN** finally 中 embedder.close() 被调用

### Requirement: close() 资源释放

系统 SHALL close() 资源释放。

#### Scenario: Embedder close() 正确关闭 HTTP client
- **WHEN** 调用 embedder.close()
- **THEN** 内部 httpx.AsyncClient 被 aclose()
- **AND** 后续访问 client 属性返回 None

#### Scenario: Embedder close() 重入安全
- **WHEN** 连续调用两次 embedder.close()
- **THEN** 第二次调用不抛异常

#### Scenario: LLMProvider close() 正确关闭
- **WHEN** 调用 llm_provider.close()
- **THEN** 内部 httpx.AsyncClient 被 aclose()

#### Scenario: LLMProvider close() 重入安全
- **WHEN** 连续调用两次 llm_provider.close()
- **THEN** 第二次调用不抛异常
