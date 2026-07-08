## ADDED Requirements

### Requirement: ES BM25 关键词检索

系统应支持通过 Elasticsearch 对 chunk text 构建倒排索引，基于 BM25 算法进行关键词检索。

#### Scenario: 关键词精确匹配（含 kb_id 过滤）
- **WHEN** 查询 "ERR-5001" 且 kb_ids=["kb1"] 且 ES 索引包含含该关键词的 chunk
- **THEN** 返回的 SearchHit 列表中，精确包含 "ERR-5001" 且 kb_id="kb1" 的 chunk 排名高于不包含的

#### Scenario: ES 不可用降级
- **GIVEN** ES 服务不可达
- **WHEN** 执行 search_by_keyword
- **THEN** 返回空列表 `[]`，不抛异常

### Requirement: ES 索引字段映射

ES 索引 `ragnexus_chunks` 应包含以下字段:

- `chunk_id` (keyword): upsert/DELETE 主键，精确匹配
- `kb_id` (keyword): term filter 过滤字段
- `heading` (text): BM25 高权重字段 (权重 ×3)
- `text` (text): BM25 标准字段
- `metadata` (object, enabled:false): 仅存储返回，不参与索引

#### Scenario: multi_match 跨字段搜索
- **WHEN** 查询 "第二十条 违约责任"
- **THEN** `heading` 匹配权重为 `text` 字段的 3 倍

### Requirement: ES 索引自动创建

启动时若 `ragnexus_chunks` 索引不存在，应自动创建并设置 mappings。

#### Scenario: 首次启动创建索引
- **GIVEN** ES 中不存在目标索引
- **WHEN** 应用启动且 ES_ENABLED=true
- **THEN** 索引被创建，含正确的 mappings 和 settings

#### Scenario: 索引已存在跳过
- **GIVEN** ES 中已存在目标索引且 mapping 兼容
- **WHEN** 应用启动
- **THEN** 不报错，正常使用已有索引

### Requirement: ES upsert 写入

上传文档时 chunk 数据应同步写入 ES 索引。

#### Scenario: chunk 写入 ES
- **WHEN** UploadDocumentUseCase 执行上传
- **THEN** chunks 数据通过 `PUT _doc/{chunk_id}` 写入 ES
- **AND** `keyword_upsert_done` 日志已打出

#### Scenario: ES upsert 写入失败
- **GIVEN** ES 不可达
- **WHEN** 调用 keyword_store.upsert(kb_id, chunks)
- **THEN** 抛出异常，由 UploadDocumentUseCase 根据双写状态矩阵决定回滚或清理

#### Scenario: ES search 不可用降级
- **GIVEN** ES 服务不可达
- **WHEN** 调用 keyword_store.search_by_keyword()
- **THEN** 返回空列表 `[]`，不抛异常（检索链路自然退化）

### Requirement: ES delete 孤儿清理

PG 写入失败时应清理已写入 ES 的 chunk。

#### Scenario: PG 失败清理 ES
- **GIVEN** ES 已写入 chunk
- **WHEN** PG 写入失败
- **THEN** 调用 `DELETE _doc/{chunk_id}` 清理 ES 孤儿

#### Scenario: 清理失败告警
- **WHEN** ES delete 也失败
- **THEN** `es_orphan_cleanup_failed` WARNING 日志打出
