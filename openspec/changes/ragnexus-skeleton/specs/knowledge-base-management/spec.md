# Knowledge Base Management

## Purpose

提供知识库（Knowledge Base）的创建能力，作为文档上传和检索的前置条件。

## Requirements

### KB 创建

- **MUST** 接受 `POST /v1/knowledge-bases:create`，请求体 `{"name": "<1-64 字符>"}`
- **MUST** 返回 `{code: 0, data: {kb_id, name, created_at}}`，`kb_id` 格式 `kb_` + nanoid(8)
- **MUST** 双字段防重名：`name`（用户输入原文）+ `name_key`（`lower(trim(name))` + UNIQUE 约束）
- **MUST** 重名时返回 409（code 1200），`message: "知识库名称已存在"`
- **MUST** name 为空或超长时返回 422（code 1000）
- **MUST** 多余字段 → 422（strict mode）

### 数据模型

- **MUST** 持久化到 `knowledge_bases` 表：`id TEXT PK, name TEXT NOT NULL, name_key TEXT UNIQUE NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW()`
- **MUST** 硬删除策略（第二期加软删除）

> 完整接口规范见 [`docs/3-pgvector-rag-cuddly-dream.md`](../../../../../docs/3-pgvector-rag-cuddly-dream.md) §1.1、§6.1、§10
