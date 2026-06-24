# Document Ingestion

## Purpose

提供文档上传 + 同步索引能力，将 .md/.txt 文件解析、切分、向量化后写入 pgvector。

## ADDED Requirements

### 文档上传

#### Scenario: 成功上传并索引
- **GIVEN** 有效的 kb_id 和 .md 文件（≤10MB）
- **WHEN** POST /v1/documents:upload
- **THEN** 返回 201，data 含 doc_id、kb_id、chunk_count；文件已解析、切分、向量化、写入 pgvector

#### Scenario: 重复上传拒绝
- **GIVEN** 同文件已上传（相同 SHA-256）
- **WHEN** 再次上传
- **THEN** 返回 409（code 1201），**解析/Embedding 前检测**

### 文档处理

- **MUST** 同步索引：请求阻塞到所有 chunk 写入 pgvector 才返回
- **MUST** doc_id = `"doc_" + sha256(file_bytes)[:16]`
- **MUST** .md 文件按标题切分（heading_aware_split），长段落回退固定窗口重叠切分（chunk_max_chars=1500, chunk_overlap=50）
- **MUST** .txt 文件固定窗口重叠切分
- **MUST** 过滤空 chunk
- **MUST** Embedding：batch_size=50, max_concurrency=5, 429 重试最多 3 次（指数退避），维度失配 → 502（code 1500）
- **MUST** 事务写入 documents + chunks 表

### 数据模型

- **MUST** `documents` 表：`doc_id PK, kb_id FK, filename, file_hash (完整 SHA-256), file_size, content_type (text/markdown | text/plain), chunk_count, uploaded_at`
- **MUST** `chunks` 表：`PRIMARY KEY (doc_id, id), kb_id FK, doc_id FK, text, metadata JSONB, embedding vector(1024)`
- **MUST** Chunk metadata 包含：`{filename, file_hash, file_size, content_type, chunk_index, heading, heading_level}`

### 响应

- **MUST** 成功返回 201：`{code: 0, data: {doc_id, kb_id, chunk_count}}`
- **MUST NOT** 返回 chunks 列表

> 完整接口规范见 [`docs/3-pgvector-rag-cuddly-dream.md`](../../../../../docs/3-pgvector-rag-cuddly-dream.md) §1.2、§6.2、§8.2、§8.4、§10
