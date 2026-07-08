## ADDED Requirements

### Requirement: Hybrid 检索双向降级时 SHALL 在 metadata 中标记降级状态

检索在 hybrid 模式下执行时，若向量检索或 BM25 检索中任一路失败，系统 SHALL 自动降级为另一路可用检索方式继续执行，并 SHALL 在返回结果的 meta 中标记 `degraded=true` 及对应的 `degraded_reason`。

#### Scenario: 向量检索失败时降级为纯 BM25
- **WHEN** hybrid 模式下向量检索抛出异常
- **THEN** 系统自动降级为纯 BM25 检索并返回结果，`meta.degraded=true`，`degraded_reason` 包含向量失败信息

#### Scenario: BM25 检索失败时降级为纯向量
- **WHEN** hybrid 模式下 BM25 检索抛出异常
- **THEN** 系统自动降级为纯向量检索并返回结果，`meta.degraded=true`，`degraded_reason` 包含 BM25 失败信息

#### Scenario: 两路检索都失败时拒绝请求
- **WHEN** hybrid 模式下向量检索和 BM25 检索均失败
- **THEN** 系统 SHALL 返回 RETRIEVAL_FAILED 错误码，不返回 200

#### Scenario: 单模式检索失败时拒绝请求
- **WHEN** 检索模式为 vector 或 bm25（非 hybrid）且对应检索失败
- **THEN** 系统 SHALL 返回对应错误码，不降级到其他模式

### Requirement: 多知识库检索 SHALL 支持 partial 容错

当一次检索请求包含多个知识库时，若部分知识库检索失败，系统 SHALL 继续返回成功库的检索结果，并 SHALL 在 meta 中标记 `partial_kb_success=true` 和 `failed_kb_ids`。

#### Scenario: 多库中单库失败时返回其余库结果
- **WHEN** 检索请求包含 3 个知识库，其中 1 个检索异常
- **THEN** 系统返回 code=0，chunk 来自成功库，`meta.partial_kb_success=true`，`failed_kb_ids` 包含失败库 ID

#### Scenario: 多库全部失败时拒绝请求
- **WHEN** 检索请求包含的所有知识库均检索失败
- **THEN** 系统 SHALL 返回 RETRIEVAL_FAILED 错误码

### Requirement: 空检索结果 SHALL 区分原因

当检索成功但未返回任何 chunk 时，系统 SHALL 在 meta 中标记 `empty_reason` 以区分空结果与系统错误。

#### Scenario: 知识库无索引 chunk 时返回空结果标记
- **WHEN** 目标知识库下没有任何 SUCCESS 状态的文档 chunk
- **THEN** 系统返回 code=0，`retrieved_chunks=[]`，`meta.empty_reason="no_indexed_chunks"`

#### Scenario: 有 chunk 但检索无命中时返回空结果标记
- **WHEN** 目标知识库有索引 chunk 但检索未命中任何结果
- **THEN** 系统返回 code=0，`retrieved_chunks=[]`，`meta.empty_reason="no_chunks_matched"`

### Requirement: query 参数边界 SHALL 通过环境变量配置

系统 SHALL 通过 `QUERY_MAX_LENGTH` 环境变量（默认 2000）配置 query 最大长度限制。空 query 或超长 query SHALL 返回 PARAM_ERROR。

#### Scenario: 空 query 被拒绝
- **WHEN** 检索请求的 query 参数为空字符串或全空格
- **THEN** 系统返回 PARAM_ERROR 错误码

#### Scenario: 超长 query 被拒绝
- **WHEN** 检索请求的 query 参数长度超过 QUERY_MAX_LENGTH
- **THEN** 系统返回 PARAM_ERROR 错误码
