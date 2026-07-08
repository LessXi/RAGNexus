# batch-reindex Specification

## ADDED Requirements

### Requirement: 批量知识库重建索引

系统 SHALL 提供 `scripts/reindex_knowledge_base.py` 脚本，接受 `--kb-id`（必填）、可选的 `--tenant-id` 和可多次传入的 `--document-id` 参数，对指定知识库下所有 `status=SUCCESS` 的文档（或 `--document-id` 指定的文档）执行重建索引。

脚本内部 SHALL 按以下流程处理每篇文档：

1. 清除该文档在 pgvector 和 Elasticsearch 中的旧 chunk
2. 将文档状态置为 `PROCESSING`
3. 提交 Celery `index_document_task` 异步任务

脚本执行中 SHALL 打印每篇文档的进度（正在处理/完成/失败），单篇失败时记录 `document_id`，不阻断其余文档继续执行。脚本结束时 SHALL 打印 `success`、`failed`、`skipped` 三项统计数字。

`PROCESSING` 中的文档 SHALL 被拒绝重复 reindex，统计进 `skipped`。

#### Scenario: 对整个知识库执行 reindex

- **GIVEN** 知识库 `kb_ecom` 下有 8 篇 `status=SUCCESS` 的文档
- **WHEN** 运行 `python scripts/reindex_knowledge_base.py --kb-id kb_ecom`
- **THEN** 8 篇文档依次被清除旧 chunk 并提交 Celery 任务
- **AND** 脚本结束时输出 `已完成：8 篇  失败：0 篇  跳过：0 篇`
- **AND** Worker 完成后，各文档 `chunks.metadata` 含 `heading_path` 和 `chunk_type`

#### Scenario: 指定文档 reindex

- **GIVEN** 知识库 `kb_ecom` 下有 8 篇文档
- **WHEN** 运行 `python scripts/reindex_knowledge_base.py --kb-id kb_ecom --document-id doc_aaa --document-id doc_bbb`
- **THEN** 仅 `doc_aaa` 和 `doc_bbb` 被 reindex
- **AND** 其余 6 篇文档不受影响

#### Scenario: 不存在的知识库

- **GIVEN** `--kb-id` 指向不存在的知识库
- **WHEN** 运行脚本
- **THEN** 脚本输出友好错误信息（如 `知识库 kb_xxx 不存在`）
- **AND** 脚本以非零退出码退出，不崩溃

#### Scenario: 某篇文档 Worker 索引失败

- **GIVEN** 知识库下有 5 篇文档，其中第 3 篇的 embedding API 临时不可用
- **WHEN** 运行脚本，Worker 在第 3 篇时失败
- **THEN** 脚本记录 `doc_id`，其余文档继续执行
- **AND** 结束时输出类似 `已完成：4 篇  失败：1 篇  跳过：0 篇`

#### Scenario: PROCESSING 中的文档被跳过

- **GIVEN** 知识库下有 1 篇 `status=PROCESSING` 的文档
- **WHEN** 运行脚本
- **THEN** 该文档不触发重复 reindex
- **AND** 统计进 `skipped`

### Requirement: 单文档强制 reindex

`POST /v1/documents/{doc_id}/reindex` API SHALL 允许 `status=SUCCESS` 的文档接受重建索引，不再限制仅 `FAILED` 状态。

`PROCESSING` 中的文档 SHALL 仍被拒绝，返回 `RESOURCE_CONFLICT` 错误。

重建流程 SHALL 与 FAILED 重试共用同一套 purge → PROCESSING → Celery task 逻辑。

#### Scenario: SUCCESS 文档可强制重建

- **GIVEN** 一篇 `status=SUCCESS` 的文档
- **WHEN** 调用 `POST /v1/documents/{doc_id}/reindex`
- **THEN** 旧 chunk 被清除，文档状态变为 `PROCESSING`
- **AND** Celery Worker 用新版 chunker 重新索引
- **AND** Worker 完成后，文档状态恢复 `SUCCESS`

#### Scenario: PROCESSING 文档拒绝重入

- **GIVEN** 一篇 `status=PROCESSING` 的文档
- **WHEN** 调用 `POST /v1/documents/{doc_id}/reindex` 或运行 reindex 脚本
- **THEN** API 返回 `RESOURCE_CONFLICT` 错误
- **AND** 脚本将其计入 `skipped`
