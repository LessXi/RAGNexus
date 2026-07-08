# async-indexing Specification

## Purpose

文档上传异步索引——upload 秒回 PROCESSING，Celery Worker 后台执行解析/分块/Embedding/双写，文档状态机（PROCESSING → SUCCESS | FAILED）。

## ADDED Requirements

### Requirement: upload 接口 MUST 异步返回 PROCESSING

POST /v1/documents:upload SHALL 在校验通过后将文档状态设为 PROCESSING，投递 Celery 索引任务后立即返回，不等待索引完成。

#### Scenario: 上传小文件立即返回 PROCESSING
- **WHEN** 上传 1KB .md 文件到有效知识库
- **THEN** 响应在 1s 内返回，`status` 为 PROCESSING（数值 2），`chunk_count` 为 0

#### Scenario: 上传大文件立即返回 PROCESSING
- **WHEN** 上传 10MB .md 文件到有效知识库
- **THEN** 响应在 1s 内返回 `status=PROCESSING`
- **AND** Celery Worker 在后台完成索引

### Requirement: Celery Worker MUST 异步执行文档索引

Celery task `index_document_task` SHALL 从数据库读取文档原文（`documents.content`），执行解析、分块、Embedding、双写，完成后更新文档状态。

#### Scenario: 索引成功
- **WHEN** Worker 成功完成所有步骤（解析→分块→Embedding→双写）
- **THEN** `documents.status` 更新为 SUCCESS（数值 1）
- **AND** `documents.chunk_count` 更新为实际 chunk 数量
- **AND** `documents.error_message` 为 null

#### Scenario: 索引失败
- **WHEN** Worker 执行过程中发生不可恢复错误（如 ES 不可用且重试耗尽）
- **THEN** `documents.status` 更新为 FAILED（数值 3）
- **AND** `documents.error_message` 包含失败原因描述
- **AND** `documents.chunk_count` 为 0

#### Scenario: 任务重试
- **WHEN** Worker 遇到可重试错误（Embedding 超时、网络抖动）
- **THEN** Celery task SHALL 最多重试 2 次，每次延迟 10 秒
- **AND** 3 次均失败后 `status=FAILED`

### Requirement: 双写 MUST 保持事务一致性

IndexingService SHALL 复用现有双写事务逻辑：pgvector 和 Elasticsearch 都成功写入后才 commit PG 事务。

#### Scenario: ES 写入失败时回滚 PG
- **WHEN** pgvector 写入成功但 ES 写入失败
- **THEN** PG 事务回滚（ROLLBACK）
- **AND** `status=FAILED`，`error_message` 包含 ES 错误信息

### Requirement: 词表同步 MUST 在索引成功后触发

文档索引成功后（status 变为 SUCCESS），SHALL 触发 `SynonymSyncUploadUseCase` 的词表同步逻辑，从新写入的 chunks 中提取术语并合并到 KB settings。

#### Scenario: 索引成功后词表同步
- **WHEN** 索引完成且 `status=SUCCESS`
- **THEN** 异步 fire-and-forget 执行词表提取与合并
- **AND** 词表同步失败不影响文档 SUCCESS 状态

### Requirement: PROCESSING 超时 MUST 被监测并标记为 FAILED

Worker 崩溃导致文档永久停留在 PROCESSING 时，系统 SHALL 有恢复机制。

#### Scenario: 超时检测
- **WHEN** 文档 `status=PROCESSING` 且 `updated_at` 超过 30 分钟
- **THEN** 定时任务（Celery beat 或后台 asyncio task）将其标记为 `status=FAILED`
- **AND** `error_message` 为 "索引超时"
