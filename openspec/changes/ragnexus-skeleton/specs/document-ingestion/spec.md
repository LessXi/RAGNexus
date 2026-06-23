# Document Ingestion

## Purpose

提供文档上传 + 同步索引能力，将 .md/.txt 文件解析、切分、向量化后写入 pgvector。

## Requirements

### 文档上传

- **MUST** 接受 `POST /v1/documents:upload`，`multipart/form-data`（`kb_id` + `file`）
- **MUST** 文件大小 ≤ 10MB（超限 → 413，code 1301）
- **MUST** 文件后缀仅 `.md` / `.txt`（其他 → 415，code 1300）
- **MUST** 文件为空或解析无有效内容 → 422（code 1400）
- **MUST** kb_id 不存在 → 404（code 1100）
- **MUST** doc_id 重复（SHA-256 前 16 位）→ 409（code 1201），**在解析/Embedding 前检测**以节省资源

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
