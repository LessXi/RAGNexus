# Comet Design Handoff

- Change: async-indexing-lifecycle
- Phase: design
- Mode: compact
- Context hash: 6bb52bd5dcab93e0f25f1faf017da0b610a51a1bf282e6d082793ef80a281860

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/async-indexing-lifecycle/proposal.md

- Source: openspec/changes/async-indexing-lifecycle/proposal.md
- Lines: 1-27
- SHA256: 05e0108f8717b25b66e1027fe8f1dc714dbbc6fb1e39a403e6554a5855603836

```md
## Why

当前文档上传在单个 HTTP 连接内同步完成解析→分块→Embedding→双写(pgvector+ES)，大文档导致超时。同时知识库和文档只能创建不能管理——传错了删不掉，索引失败无法重试，缺乏完整生命周期运维能力。

## What Changes

- **BREAKING**: `POST /v1/documents:upload` 返回 `status=PROCESSING` 而非同步等待索引完成，`chunk_count` 在索引完成前为 0
- **BREAKING**: `GET /v1/knowledge-bases/tree` 的 `documents[].status` 从 `"completed"` 扩展为三种状态（PROCESSING/SUCCESS/FAILED），新增 `error_message` 字段
- 引入 Celery + Redis 架构，upload 秒回后由后台 Worker 执行索引
- `documents` 表新增 `status`/`content`/`error_message` 列
- 新增 `DocumentPort` + `PgDocumentRepository`，解除 KB 仓库的文档操作耦合
- 拆分 `UploadUseCase`，抽取 `IndexingService`（复用现有索引代码）
- 新增 6 个 HTTP 端点：文档状态查询、删除、重试索引；知识库详情、更新、删除
- `tree` 接口适配三种文档状态，支持前端轮询
- admin 前端适配：上传页异步响应、列表页状态展示/轮询/操作入口、编辑/确认弹窗

## Capabilities

### New Capabilities

- `async-indexing`: 异步文档索引——Celery Worker 后台执行解析/分块/Embedding/双写，文档状态机（PROCESSING→SUCCESS/FAILED），失败重试
- `doc-lifecycle`: 文档生命周期管理——状态查询（GET /documents/{id}）、删除（DELETE，级联清理 pgvector+ES）、失败重试（POST reindex）
- `kb-lifecycle`: 知识库生命周期管理——详情查询（GET /knowledge-bases/{id}，含完整 settings）、更新（PATCH name/description/settings）、级联删除（DELETE，含 PROCESSING 保护）

### Modified Capabilities

<!-- 无已有 spec 受影响 -->
```

## openspec/changes/async-indexing-lifecycle/design.md

- Source: openspec/changes/async-indexing-lifecycle/design.md
- Lines: 1-61
- SHA256: a1416fc619af662a9c34e2698cd3c424bebf20d7105eb71822ea62a3817d6a4e

```md
## Context

RAGNexus 当前 upload 流程在单个 HTTP 连接内同步执行全部索引步骤（解析→分块→Embedding→双写 pgvector+ES），大文档导致超时。同时知识库和文档缺少生命周期管理——只能创建不能修改删除。改造后 upload 秒回 PROCESSING，Celery Worker 后台异步索引；补齐知识库和文档的 CRUD 运维接口。

**架构约束**：Clean Architecture (domain→application→adapters)，纯 async 全链路，Port-Adapter 模式，Docker Compose 部署。

## Goals / Non-Goals

**Goals:**
- upload 接口 <1s 返回，索引由 Celery Worker 后台异步执行
- 文档三态状态机：PROCESSING → SUCCESS | FAILED，支持重试、超时恢复
- 知识库 CRUD：详情查询（含完整 settings）、更新（name/description/settings）、级联删除
- 文档 CRUD：状态查询、删除（级联清理 pgvector+ES）、失败重试
- 前端适配异步体验：状态轮询、操作入口

**Non-Goals:**
- 不改变检索/Embedding/分块算法
- 不改变现有双写事务逻辑
- 不新增用户认证体系
- 不修改 admin 检索页

## Decisions

### D1: Celery + Redis 作为任务队列

**选 Celery 而非 arq/内置 asyncio**。Celery 是业界标准，监控/重试/超时/结果存储开箱即用。RAGNexus 全链路 async 的索引逻辑在 Celery task 内用 `asyncio.run()` 桥接一次即可。Worker 独立进程，独立 DB 连接池。

### D2: 独立 DocumentPort + PgDocumentRepository

当前 `PgKnowledgeBaseRepository` 同时管理 KB 和文档操作，职责过重。抽取 `DocumentPort` Protocol，`PgDocumentRepository` 实现，解除耦合。`KnowledgeBasePort` 扩展 `update`/`delete` 方法。

### D3: UploadUseCase 拆分为建记录 + 投递任务

现有 `UploadDocumentUseCase.execute()` 拆为两步：
1. API 侧：校验 → 建 documents 行（`content` 落库，`status=PROCESSING`）→ `task.delay(doc_id)` → 返回
2. Worker 侧：`IndexingService.execute(doc_id)` → 读 content → 复用现有 parser/chunker/embedder/store → 更新 status

**索引代码零改动**，只改变调用方和调用时机。

### D4: 整数状态枚举 + 状态转换矩阵

`DocStatus` IntEnum：SUCCESS=1, PROCESSING=2, FAILED=3。状态转换：

```
upload → PROCESSING → Worker 完成 → SUCCESS
                   → Worker 失败 → FAILED
reindex          → PROCESSING (仅从 FAILED)
```

### D5: 统一 purge_document_chunks 方法

删文档、删知识库、reindex 三处共用的双存储清理逻辑，抽取为 `purge_document_chunks(doc_id)`，确保 ES 不被遗漏导致脏数据。

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| Celery task 内 `asyncio.run()` 与 API event loop 隔离，无冲突 | IndexingService 自身是 async class，`asyncio.run()` 创建独立 loop |
| Worker 崩溃 → 文档永久 PROCESSING | Celery beat 定时任务标记超时 → FAILED（阈值 30 分钟，可配） |
| 删库时 Worker 正在索引该库文档 | 删库前 `has_processing(kb_id)` 检查，拒绝删除 |
| ES/PG 双写一致性问题 | 复用现有双写事务逻辑（双成功才 commit） |
```

## openspec/changes/async-indexing-lifecycle/tasks.md

- Source: openspec/changes/async-indexing-lifecycle/tasks.md
- Lines: 1-59
- SHA256: aa25c3738bba04690e7459f3e8bd00888f9558e0d75085da40d8363b29953686

```md
## 1. 基础设施

- [ ] 1.1 docker-compose.yml 增加 Redis + Celery worker 服务
- [ ] 1.2 pyproject.toml 增加 celery[redis]>=5.4.0 + redis>=5.0.0 依赖
- [ ] 1.3 Settings 增加 CELERY_BROKER_URL / CELERY_RESULT_BACKEND / INDEX_TIMEOUT_MINUTES
- [ ] 1.4 Alembic migration: documents 表加 status INT, content TEXT, error_message TEXT 列
- [ ] 1.5 更新 docs/sql/schema.sql 对齐实际表结构（同步 knowledge_bases 已有列）

## 2. 领域层

- [ ] 2.1 models.py: 新增 Document dataclass + DocStatus IntEnum
- [ ] 2.2 models.py: UploadResult 增加 status 字段
- [ ] 2.3 models.py: DocNode / KBNode 增加 error_message + status 适配
- [ ] 2.4 ports.py: 新增 DocumentPort Protocol
- [ ] 2.5 ports.py: KnowledgeBasePort 扩展 update/delete/has_processing 方法
- [ ] 2.6 新增 adapters/document/pg.py → PgDocumentRepository
- [ ] 2.7 重构 PgKnowledgeBaseRepository: kb update/delete，移除嵌入的文档操作
- [ ] 2.8 调整 composition.py DI 注入新的 document_repo + 更新的 kb_repo

## 3. 异步索引核心

- [ ] 3.1 新增 celery_app.py: Celery 实例 + 配置 + beat schedule（超时检测）
- [ ] 3.2 新增 application/indexing_service.py: 复用 parser/chunker/embedder/store
- [ ] 3.3 新增 tasks/indexing.py: index_document_task（asyncio.run 桥接）+ 超时检测 task
- [ ] 3.4 重构 UploadDocumentUseCase: 拆分为 create_document_record + task.delay()
- [ ] 3.5 新增 purge_document_chunks 工具方法（PG CASCADE + ES delete）
- [ ] 3.6 调整 SynonymSyncUploadUseCase 触发时机：upload 创建记录后暂不触发，索引 SUCCESS 后触发

## 4. 运维 API

- [ ] 4.1 新增 GET /v1/documents/{doc_id} 路由 + DocumentQueryUseCase
- [ ] 4.2 新增 DELETE /v1/documents/{doc_id} 路由 + DocumentDeleteUseCase
- [ ] 4.3 新增 POST /v1/documents/{doc_id}/reindex 路由 + DocumentReindexUseCase
- [ ] 4.4 新增 GET /v1/knowledge-bases/{kb_id} 路由 + KnowledgeBaseDetailUseCase
- [ ] 4.5 新增 PATCH /v1/knowledge-bases/{kb_id} 路由 + KnowledgeBaseUpdateUseCase
- [ ] 4.6 新增 DELETE /v1/knowledge-bases/{kb_id} 路由 + KnowledgeBaseDeleteUseCase
- [ ] 4.7 tree 接口适配: DocNode 增加 status + error_message，三种状态全部返回

## 5. 前端适配

- [ ] 5.1 types/api.ts: 新增 DocStatus 枚举, DocumentDetail, UpdateKBRequest 等类型
- [ ] 5.2 documentService.ts: 新增 deleteDocument / reindexDocument
- [ ] 5.3 knowledgeBaseService.ts: 新增 fetchDetail / updateKB / deleteKB
- [ ] 5.4 上传页: 适配 PROCESSING 响应（"已提交，正在后台索引" Toast）
- [ ] 5.5 列表页: 三种状态 StatusBadge（黄/绿/红）+ PROCESSING 时 3s 轮询
- [ ] 5.6 列表页: 文档删除/重试按钮 + KB 编辑/删除入口
- [ ] 5.7 新增 ConfirmDialog 组件（删文档/删 KB 复用）
- [ ] 5.8 新增 EditKnowledgeBaseDialog 组件（name + description + settings JSON）
- [ ] 5.9 集成测试: 三页导航正常，完整操作路径验证

## 6. 测试与文档

- [ ] 6.1 单元测试: IndexingService、DocumentRepository、KnowledgeBaseRepository
- [ ] 6.2 集成测试: 异步上传→轮询→检索命中 完整链路
- [ ] 6.3 集成测试: ES 不可用→FAILED→恢复→reindex→SUCCESS
- [ ] 6.4 集成测试: knowledge-base CRUD 完整覆盖
- [ ] 6.5 集成测试: 跨租户隔离（GET/PATCH/DELETE 均返回 NOT_FOUND）
- [ ] 6.6 E2E 测试: PROCESSING 文档 DELETE/delete-KB 被拒绝
- [ ] 6.7 更新 README.md 补充 Worker 启动命令和异步索引说明
```

## openspec/changes/async-indexing-lifecycle/specs/async-indexing/spec.md

- Source: openspec/changes/async-indexing-lifecycle/specs/async-indexing/spec.md
- Lines: 1-68
- SHA256: 49fb0e9b4fa7359e66f6983c368b0ca5a94c0ff945de90acdd19b715ddafb644

```md
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
```

## openspec/changes/async-indexing-lifecycle/specs/doc-lifecycle/spec.md

- Source: openspec/changes/async-indexing-lifecycle/specs/doc-lifecycle/spec.md
- Lines: 1-78
- SHA256: c2aee3db941b9b7619cceb6cf227a708803456c198b6eb4d4e430894ec6a3cdb

```md
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
```

## openspec/changes/async-indexing-lifecycle/specs/kb-lifecycle/spec.md

- Source: openspec/changes/async-indexing-lifecycle/specs/kb-lifecycle/spec.md
- Lines: 1-68
- SHA256: f683f746a911bff236f3ff3d97244f975dbf55596fffc983b0f975cf41445279

```md
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
```

