# Vector Retrieval

## Purpose

提供纯向量检索能力，给定查询文本，在指定知识库中检索最相关的文档片段。

## Requirements

### 检索请求

- **MUST** 接受 `POST /v1/rag:retrieve`，请求体 `{"query": "<1-2000 字符>", "kb_ids": ["<1-5 个>"], "top_k": <1-50>}`
- **MUST** strict 模式：多余字段（包括 `filter`）→ 422（code 1000）
- **MUST** kb_ids 任一不存在 → 404（code 1100）
- **MUST** query 为空 / kb_ids 为空 / top_k 越界 → 422（code 1000）

### 检索逻辑

- **MUST** 先 Embedding query → 再向量检索
- **MUST** 评分：余弦相似度 `1 - (embedding <=> query_vector)`，6 位小数，越大越相关
- **MUST** 跨 KB 全局 top_k（不接受 KB 级别偏置的复杂性）
- **MUST** pgvector HNSW 索引（`vector_cosine_ops`）

### 日志

- **MUST** fire-and-forget 写 `retrieve_logs` 表（`asyncio.create_task`，不阻塞响应）
- **MUST** 日志失败被吞掉，不影响主流程
- **MUST** 记录：kb_ids, query, top_k, hit_count, latency_ms

### 响应

- **MUST** 返回 `{code: 0, data: {total, hits: [{chunk_id, kb_id, doc_id, score, text, metadata}]}}`
- **MUST** 空结果返回 `total: 0, hits: []`（非错误）
- **MUST** 错误时返回 code 1501（向量库失败）

### 数据模型

- **MUST** `retrieve_logs` 表：`id BIGSERIAL PK, kb_ids TEXT[], query, top_k, hit_count, latency_ms, created_at`

> 完整接口规范见 [`docs/3-pgvector-rag-cuddly-dream.md`](../../../../../docs/3-pgvector-rag-cuddly-dream.md) §1.3、§6.3、§8.2、§10
