## ADDED Requirements

### Requirement: 改写启用开关
系统 MUST 通过 `REWRITE_ENABLED` 配置项控制是否启用查询改写。默认值 MUST be `false`（禁用）。

#### Scenario: 禁用时直通
- **WHEN** `REWRITE_ENABLED=false`（默认）
- **THEN** 检索 MUST 使用原始 query 进行 embedding，不做改写

#### Scenario: 启用时执行改写
- **WHEN** `REWRITE_ENABLED=true`
- **THEN** embedding 之前 MUST 执行查询改写

### Requirement: HTTP 契约零变化
查询改写 MUST NOT 改变 `POST /v1/rag:retrieve` 的请求 schema 或响应 schema。调用方 MUST NOT 能感知差异。

#### Scenario: 请求不变
- **WHEN** 调用方发送检索请求
- **THEN** 请求体格式 MUST 与第一期完全一致

#### Scenario: 响应不变
- **WHEN** 调用方收到检索响应
- **THEN** 响应体格式 MUST 与第一期完全一致
- **THEN** 响应 MUST NOT 包含改写相关信息（如 `original_query`、`rewritten_query`）

### Requirement: 一次 LLM 调用完成判断和改写
系统 MUST 在一次 LLM 调用中同时完成"是否需要改写"的判断和"执行改写"。

#### Scenario: 需要改写
- **WHEN** 查询包含口语化表达、指代词、或语义模糊
- **THEN** LLM MUST 输出 `needs_rewrite: true` 和 `rewritten_query`
- **THEN** embedding MUST 使用改写后的 query

#### Scenario: 不需要改写
- **WHEN** 查询已包含明确的关键词、专业术语，语义清晰
- **THEN** LLM MUST 输出 `needs_rewrite: false` 和 `rewritten_query` 等于原始 query
- **THEN** embedding MUST 使用原始 query

### Requirement: LLM 调用降级
查询改写 MUST 保证接口不因 LLM 不可用而中断。

#### Scenario: LLM 调用失败
- **WHEN** LLM 调用超时、返回错误、或 JSON 解析失败
- **THEN** MUST 使用原始 query，MUST NOT 抛异常
- **THEN** 降级决策 MUST 在 LLMRewriteProvider 内部完成

### Requirement: 改写缓存
系统 MUST 提供改写缓存，对相同或相似的 query 避免重复 LLM 调用。

#### Scenario: 缓存命中
- **WHEN** 当前 query 的向量与缓存中某条目的向量 cosine 相似度 ≥ 0.95
- **THEN** MUST 直接使用缓存的改写结果，跳过 LLM 调用

#### Scenario: KB 写入失效
- **WHEN** 某 KB 的文档上传完成
- **THEN** MUST 清空该 KB 的全部改写缓存

### Requirement: `reason` 字段仅日志使用
LLM 返回的改写原因 MUST NOT 影响业务逻辑。

#### Scenario: reason 不影响逻辑
- **WHEN** LLM 返回 `reason` 字段
- **THEN** 该字段 MUST 仅用于日志记录，MUST NOT 影响改写结果的输出
- **WHEN** `reason` 为空或缺失
- **THEN** MUST NOT 触发降级，MUST NOT 影响 rewrite 结果

> 实现参考: `docs/5-query-rewrite-silent-scribe.md`（320 行工程规范）
