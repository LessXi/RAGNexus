# Knowledge Base Management

## Purpose

提供知识库（Knowledge Base）的创建能力，作为文档上传和检索的前置条件。

## ADDED Requirements

### Requirement: KB 创建
系统 **SHALL** KB 创建。


#### Scenario: 成功创建知识库
- **GIVEN** 有效的 name（1-64 字符）
- **WHEN** 客户端 POST /v1/knowledge-bases:create
- **THEN** 返回 200，data 包含 kb_id（kb_ + nanoid(8)）、name、created_at（ISO 8601）

#### Scenario: 重名拒绝
- **GIVEN** 已存在 name_key 相同的 KB
- **WHEN** 客户端用相同名称创建
- **THEN** 返回 409，code 1200，message "知识库名称已存在"

### Requirement: 数据模型

- **MUST** 持久化到 `knowledge_bases` 表：`id TEXT PK, name TEXT NOT NULL, name_key TEXT UNIQUE NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW()`
- **MUST** 硬删除策略（第二期加软删除）

> 完整接口规范见 [`docs/3-pgvector-rag-cuddly-dream.md`](../../../../../docs/3-pgvector-rag-cuddly-dream.md) §1.1、§6.1、§10

#### Scenario: Normal operation
- **WHEN** 系统接收到符合规范的请求
- **THEN** 按 MUST 语义返回预期响应
