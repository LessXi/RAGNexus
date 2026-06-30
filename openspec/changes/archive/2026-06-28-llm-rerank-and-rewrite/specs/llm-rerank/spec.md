## ADDED Requirements

### Requirement: 重排启用开关
系统 MUST 通过 `RERANK_ENABLED` 配置项控制是否启用 LLM 重排。默认值 MUST be `false`（禁用）。

#### Scenario: 禁用时直通
- **WHEN** `RERANK_ENABLED=false`（默认）
- **THEN** 检索结果 MUST 直接返回向量排序结果，不做重排

#### Scenario: 启用时执行重排
- **WHEN** `RERANK_ENABLED=true`
- **THEN** 向量召回后、返回前，MUST 执行 LLM 重排

### Requirement: HTTP 契约零变化
重排 MUST NOT 改变 `POST /v1/rag:retrieve` 的请求 schema、响应 schema 或 `score` 语义。

#### Scenario: 请求不变
- **WHEN** 调用方发送检索请求
- **THEN** 请求体格式（`query` / `kb_ids` / `top_k`）MUST 与第一期完全一致
- **THEN** 请求体 MUST NOT 包含任何重排相关字段

#### Scenario: 响应不变
- **WHEN** 调用方收到检索响应
- **THEN** 响应体格式 MUST 与第一期完全一致
- **THEN** `hits[].score` MUST 始终为向量原始分（1 - cosine distance），MUST NOT 被重排覆盖
- **THEN** 响应 MUST NOT 包含 `rerank_score` 或任何重排相关字段
- **THEN** `hits` 的排列顺序 MAY 受重排影响，但调用方 MUST NOT 能感知差异

### Requirement: `top_k` 语义不变
`top_k` MUST 始终等于最终返回的 chunk 数量。

#### Scenario: 候选数计算
- **WHEN** 启用重排
- **THEN** 内部 MUST 召回更多候选：`candidate_k = max(top_k × candidate_multiplier, top_k + min_candidates)`
- **THEN** 重排后 MUST 裁回 `top_k` 条返回
- **WHEN** 禁用重排
- **THEN** `candidate_k` MUST 等于 `top_k`（不额外召回）

### Requirement: LLM 调用降级
LLM 重排 MUST 保证接口不因 LLM 不可用而中断。

#### Scenario: LLM 调用失败
- **WHEN** LLM 调用超时、返回错误、或 JSON 解析失败
- **THEN** MUST 返回原始向量排序结果，MUST NOT 抛异常
- **THEN** 降级决策 MUST 在 LLMRerankProvider 内部完成，MUST NOT 传播到 use case 或 HTTP 层

### Requirement: 重排缓存
系统 MUST 提供重排缓存，对相同或相似的 query 避免重复 LLM 调用。

#### Scenario: 缓存命中
- **WHEN** 当前 query 的向量与缓存中某条目的向量 cosine 相似度 ≥ 0.95
- **THEN** MUST 直接使用缓存分，跳过 LLM 调用

#### Scenario: 部分命中
- **WHEN** 部分候选 chunk 有缓存分、部分没有
- **THEN** 未命中的 chunk MUST 送 LLM 打分，缓存的 chunk 分 MUST 作为 Prompt 标尺参考

#### Scenario: KB 写入失效
- **WHEN** 某 KB 的文档上传完成
- **THEN** MUST 清空该 KB 的全部缓存条目

### Requirement: 候选截断
LLM 重排的输入候选数 MUST 有上限，防止 payload 过大。

#### Scenario: 候选上限
- **WHEN** `candidate_k` 计算值超过 `max_candidates`（默认 20）
- **THEN** MUST 截断为 `max_candidates` 条
- **WHEN** 截断发生
- **THEN** MUST 优先保留向量分最高的候选

### Requirement: 日志记录
重排过程 MUST 输出结构化日志，支持运维排查。

#### Scenario: 日志输出
- **WHEN** 重排完成
- **THEN** MUST 记录 `BIZ_EVENT` 事件，包含：query、候选数、LLM 是否调用、缓存命中率、耗时
- **WHEN** LLM 调用失败
- **THEN** MUST 记录 `BIZ_EVENT` 事件，标记降级原因

> 实现参考: `docs/4-llm-rerank-silent-judge.md`（739 行工程规范）
