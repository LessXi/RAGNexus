## MODIFIED Requirements

### Requirement: 并发双写 PG + ES

上传文档时 chunk 数据应并发写入 PG 和 ES，PG 事务的 commit 由 UploadDocumentUseCase 外部控制。

#### Scenario: 并发双写成功
- **WHEN** UploadDocumentUseCase 执行上传
- **THEN** ES upsert 和 PG 写入在 asyncio.gather 中并发运行
- **AND** 两路均成功后 PG 事务 commit
- **AND** 上传返回成功

#### Scenario: PG 失败且 ES 成功
- **GIVEN** ES 写入成功
- **WHEN** PG 写入失败（如 doc_id 重复）
- **THEN** 调用 `keyword_store.delete()` 清理 ES 孤儿
- **AND** 上传返回失败

#### Scenario: PG 失败且 ES 失败
- **WHEN** PG 和 ES 均写入失败
- **THEN** PG 事务自动 rollback
- **AND** 上传返回失败

#### Scenario: PG 成功且 ES 失败
- **WHEN** PG 写入成功但 ES 写入失败
- **THEN** PG 事务 rollback
- **AND** 上传返回失败
