# kb-lifecycle Specification

## Purpose

知识库生命周期管理——详情查询（含完整 settings 词表）、更新名称/描述/词表、级联删除（含 PROCESSING 文档保护）。

## ADDED Requirements

### Requirement: GET /v1/knowledge-bases/{kb_id} MUST 返回完整详情

系统 SHALL 为每个知识库提供详情查询接口，返回名称、描述、完整 settings JSON、文档数量和创建时间。

#### Scenario: 查询知识库详情
- **WHEN** 查询存在且属于当前租户的知识库
- **THEN** 响应包含 `name`、`description`、`settings`（完整 JSON，含 synonyms 和 rewrite_hint）、`document_count`、`created_at`、`updated_at`

#### Scenario: 跨租户查询
- **WHEN** 用租户 A 的 API Key 查询属于租户 B 的知识库
- **THEN** 返回 NOT_FOUND，不暴露知识库存在于其他租户的信息

### Requirement: PATCH /v1/knowledge-bases/{kb_id} MUST 支持部分更新

更新知识库 SHALL 支持 name、description、settings 三个字段的部分更新，至少传一个字段。

#### Scenario: 更新 settings 词表
- **WHEN** PATCH 传入合法 settings JSON（含 synonyms）
- **THEN** settings 整段替换（覆盖，非 deep merge），下次 retrieve 词表即时生效
- **AND** 不需要触发文档 reindex

#### Scenario: 更新名称和描述
- **WHEN** PATCH 传入 `name` 和 `description`
- **THEN** 知识库名称和描述更新
- **AND** `GET /v1/knowledge-bases/tree` 反映新名称

#### Scenario: 传入非法 settings
- **WHEN** settings JSON 中 synonyms 组的 terms 或 expand 为空数组
- **THEN** 返回 PARAM_ERROR，提示结构不合法

#### Scenario: 不传任何字段
- **WHEN** PATCH 请求体不包含 name、description、settings 任一字段
- **THEN** 返回 PARAM_ERROR，提示至少传一个字段

### Requirement: DELETE /v1/knowledge-bases/{kb_id} MUST 级联删除并保护进行中任务

删除知识库 SHALL 先检查是否包含 PROCESSING 文档（Worker 可能仍在执行），通过后级联删除全部文档和 chunks。

#### Scenario: 删除无 PROCESSING 文档的知识库
- **WHEN** 知识库下所有文档状态均为 SUCCESS 或 FAILED
- **THEN** 逐文档调用 purge_document_chunks 清理 pgvector+ES
- **AND** 删除 documents 记录
- **AND** 删除 knowledge_bases 记录
- **AND** `GET /v1/knowledge-bases/tree` 不再包含该知识库

#### Scenario: 删除包含 PROCESSING 文档的知识库被拒绝
- **WHEN** 知识库下存在状态为 PROCESSING 的文档
- **THEN** 返回错误，提示库内有文档正在索引中，拒绝删除

### Requirement: 所有运维接口 MUST 校验租户归属

GET / PATCH / DELETE 知识库和文档接口 SHALL 通过 `get_current_tenant` 校验资源归属，跨租户访问统一返回 NOT_FOUND。

#### Scenario: 跨租户 PATCH 知识库
- **WHEN** 用租户 A 的 API Key 更新租户 B 的知识库
- **THEN** 返回 NOT_FOUND

#### Scenario: 跨租户 DELETE 知识库
- **WHEN** 用租户 A 的 API Key 删除租户 B 的知识库
- **THEN** 返回 NOT_FOUND
