# vector-retrieval Specification

## Purpose
TBD - created by archiving change ragnexus-skeleton. Update Purpose after archive.
## Requirements
### Requirement: 检索请求
系统 **SHALL** 检索请求。

#### Scenario: 成功检索
- **GIVEN** 有效的 query、存在的 kb_ids、合法的 top_k
- **WHEN** POST /v1/rag:retrieve
- **THEN** 返回 200，data 含 total 和 hits[] 列表，按 score 降序排列

#### Scenario: 多余字段拒绝
- **GIVEN** 请求体含 filter 字段（不在 schema 中）
- **WHEN** POST /v1/rag:retrieve
- **THEN** 返回 422（code 1000），strict 模式拦截

### Requirement: 检索逻辑

- **MUST** 先 Embedding query → 再向量检索
- **MUST** 评分：余弦相似度 `1 - (embedding <=> query_vector)`，6 位小数，越大越相关
- **MUST** 跨 KB 全局 top_k（不接受 KB 级别偏置的复杂性）
- **MUST** pgvector HNSW 索引（`vector_cosine_ops`）

#### Scenario: Normal operation
- **WHEN** 系统接收到符合规范的请求
- **THEN** 按 MUST 语义返回预期响应

### Requirement: 日志

- **MUST** fire-and-forget 写 `retrieve_logs` 表（`asyncio.create_task`，不阻塞响应）
- **MUST** 日志失败被吞掉，不影响主流程
- **MUST** 记录：kb_ids, query, top_k, hit_count, latency_ms

#### Scenario: Normal operation
- **WHEN** 系统接收到符合规范的请求
- **THEN** 按 MUST 语义返回预期响应

### Requirement: 响应

- **MUST** 返回 `{code: 0, data: {total, hits: [{chunk_id, kb_id, doc_id, score, text, metadata}]}}`
- **MUST** 空结果返回 `total: 0, hits: []`（非错误）
- **MUST** 错误时返回 code 1501（向量库失败）

#### Scenario: Normal operation
- **WHEN** 系统接收到符合规范的请求
- **THEN** 按 MUST 语义返回预期响应

### Requirement: 数据模型

- **MUST** `retrieve_logs` 表：`id BIGSERIAL PK, kb_ids TEXT[], query, top_k, hit_count, latency_ms, created_at`

> 完整接口规范见 [`docs/3-pgvector-rag-cuddly-dream.md`](../../../../../docs/3-pgvector-rag-cuddly-dream.md) §1.3、§6.3、§8.2、§10

#### Scenario: Normal operation
- **WHEN** 系统接收到符合规范的请求
- **THEN** 按 MUST 语义返回预期响应

