# doc-lifecycle Specification

## Purpose

文档生命周期管理——状态查询、删除（级联清理 pgvector+ES）、失败重试索引、tree 接口返回三种文档状态。

## ADDED Requirements

### Requirement: GET /v1/documents/{doc_id} MUST 返回文档详情

系统 SHALL 为每个文档提供状态查询接口，返回文档元数据和索引进度。

#### Scenario: 查询 PROCESSING 文档
- **WHEN** 查询刚上传正在索引的文档
- **THEN** 响应 `status` 为 PROCESSING（数值 2），`chunk_count` 为 0，`error_message` 为 null

#### Scenario: 查询 SUCCESS 文档
- **WHEN** 查询索引完成的文档
- **THEN** 响应 `status` 为 SUCCESS（数值 1），`chunk_count` > 0，`error_message` 为 null

#### Scenario: 查询 FAILED 文档
- **WHEN** 查询索引失败的文档
- **THEN** 响应 `status` 为 FAILED（数值 3），`error_message` 非空

#### Scenario: 跨租户查询
- **WHEN** 用租户 A 的 API Key 查询属于租户 B 的文档
- **THEN** 返回 NOT_FOUND，不暴露文档存在于其他租户的信息

### Requirement: DELETE /v1/documents/{doc_id} MUST 级联清理数据

删除文档 SHALL 同时清理 pgvector 中的向量 chunks 和 Elasticsearch 中的关键词索引。

#### Scenario: 删除 SUCCESS 文档
- **WHEN** 删除状态为 SUCCESS 的文档
- **THEN** 文档记录删除，pgvector chunks 清理（CASCADE），ES keyword 索引清理
- **AND** `GET /v1/knowledge-bases/tree` 不再包含该文档
- **AND** retrieve 接口不再命中该文档的 chunks

#### Scenario: 删除 FAILED 文档
- **WHEN** 删除状态为 FAILED 的文档
- **THEN** 文档记录删除，残留 chunks（如有）一并清理
- **AND** `GET /v1/knowledge-bases/tree` 不再包含该文档

#### Scenario: 删除 PROCESSING 文档被拒绝
- **WHEN** 尝试删除状态为 PROCESSING 的文档
- **THEN** 返回错误，提示文档正在索引中，拒绝删除

### Requirement: POST /v1/documents/{doc_id}/reindex MUST 重新索引失败文档

对索引失败的文档 SHALL 提供重试机制，清理残留数据后重新投递 Celery 索引任务。

#### Scenario: 重试 FAILED 文档
- **WHEN** 对 FAILED 文档发起 reindex
- **THEN** 先清理残留 chunks（purge_document_chunks）
- **AND** 文档状态重置为 PROCESSING
- **AND** 投递 Celery 索引任务
- **AND** 最终 Worker 完成后变为 SUCCESS

#### Scenario: 重试 SUCCESS 文档被拒绝
- **WHEN** 对 SUCCESS 文档发起 reindex
- **THEN** 返回错误，已成功的文档不允许重试

#### Scenario: 重试 PROCESSING 文档被拒绝
- **WHEN** 对 PROCESSING 文档发起 reindex
- **THEN** 返回错误，正在索引中的文档不允许重试

### Requirement: tree 接口 MUST 返回三种文档状态

GET /v1/knowledge-bases/tree SHALL 返回所有文档（不限于 SUCCESS），包含状态和错误信息。

#### Scenario: tree 包含所有状态文档
- **WHEN** 知识库下有 PROCESSING、SUCCESS、FAILED 三种文档
- **THEN** `documents` 数组包含全部三种文档
- **AND** 每个文档节点包含 `status`（整数）和 `error_message`（字符串或 null）

#### Scenario: PROCESSING 文档的 chunk_count
- **WHEN** tree 中包含 PROCESSING 文档
- **THEN** 该文档的 `chunk_count` 为 0（索引尚未完成）
