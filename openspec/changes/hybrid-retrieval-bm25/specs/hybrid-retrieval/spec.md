## ADDED Requirements

### Requirement: RRF 融合

系统应支持对向量召回和关键词召回的结果进行 RRF (Reciprocal Rank Fusion) 融合。

#### Scenario: 两路正常融合
- **WHEN** vec_hits 和 kw_hits 均有结果
- **THEN** 每个 chunk 的 RRF 分 = Σ 1/(RRF_K + rank_i)
- **AND** 结果按 RRF 分降序排列

#### Scenario: 单路自动退化
- **WHEN** kw_hits=[] (ES 禁用或 0 结果)
- **THEN** RRF 结果 = 仅 vec_hits（按 RRF 单路分排序），不抛异常

#### Scenario: 跨来源去重
- **WHEN** 同一 chunk_id 同时出现在两路
- **THEN** 该 chunk 的 RRF 分 = 向量路 rank 贡献 + 关键词路 rank 贡献

### Requirement: 检索模式控制

系统应通过 `RETRIEVAL_MODE` 配置控制检索行为。

#### Scenario: hybrid 模式
- **GIVEN** RETRIEVAL_MODE="hybrid"
- **WHEN** 执行检索
- **THEN** 两路并行召回 → RRF 融合

#### Scenario: vector 模式
- **GIVEN** RETRIEVAL_MODE="vector"
- **WHEN** 执行检索
- **THEN** 仅向量召回，kw_hits 不执行

#### Scenario: bm25 模式
- **GIVEN** RETRIEVAL_MODE="bm25"
- **WHEN** 执行检索
- **THEN** 仅 BM25 召回，vec_hits 不执行

### Requirement: 并发双路召回

向量召回和关键词召回应通过 asyncio.gather 并发执行。

#### Scenario: 并行执行
- **WHEN** 执行检索
- **THEN** `store.search_by_vector()` 和 `keyword_store.search_by_keyword()` 并发运行
- **AND** 总耗时 ≈ max(向量耗时, ES 耗时)，非两者之和

### Requirement: CANDIDATE_K 控制召回量

每路召回条数由 `CANDIDATE_K` 统一控制。

#### Scenario: 默认召回量
- **GIVEN** CANDIDATE_K=20
- **WHEN** 执行检索
- **THEN** 每路各召回 20 条

### Requirement: RRF 分覆盖 SearchHit.score

RRF 融合后 SearchHit.score 应被 RRF 分覆盖，下游透明。

#### Scenario: score 语义
- **WHEN** RRF 融合完成
- **THEN** 每个 SearchHit.score = RRF 分
- **AND** 下游 reranker 和 API 响应使用该值

### Requirement: ES 禁用时启动不报错

ES_ENABLED=false 时应用应正常启动，检索自动退化为纯向量。

#### Scenario: ES 禁用启动
- **GIVEN** ES_ENABLED=false

- **THEN** 不创建 ES 连接池
- **AND** keyword_store = NoopKeywordSearchProvider

#### Scenario: bm25 模式但 ES 未启用
- **GIVEN** RETRIEVAL_MODE="bm25" 且 ES_ENABLED=false
- **WHEN** 应用启动
- **THEN** 打出 WARNING 日志：bm25 模式下 ES 未启用，检索将返回空结果
