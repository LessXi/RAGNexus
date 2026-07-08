## MODIFIED Requirements

### Requirement: 双路并行召回 + RRF 融合

RetrieveUseCase 应从单路向量召回改为双路并行：语义路用 `embed(改写后 query)` 搜 pgvector，关键词路用原始 query 搜 ES，结果经 RRF 融合。

#### Scenario: 混合检索全链路
- **WHEN** 执行检索且 RETRIEVAL_MODE="hybrid"
- **THEN** `store.search_by_vector(rewrite_vec, CANDIDATE_K, kb_ids)` 和 `keyword_store.search_by_keyword(original_query, CANDIDATE_K, kb_ids)` 并发运行
- **AND** 结果经 `rrf_fuse()` 融合
- **AND** 融合结果送 reranker.rerank()

#### Scenario: vector 模式
- **WHEN** RETRIEVAL_MODE="vector"
- **THEN** 仅执行向量召回，kw_hits=[]，RRF 自然退化为纯向量排序

#### Scenario: bm25 模式
- **WHEN** RETRIEVAL_MODE="bm25"
- **THEN** 仅执行关键词召回，vec_hits=[]，RRF 自然退化为纯 BM25 排序

### Requirement: 双 query embedding

检索时应同时计算 `embed(改写后 query)` 用于向量搜索，`embed(原始 query)` 用于 rerank 缓存匹配。

#### Scenario: rewrite 启用时双 embedding
- **WHEN** 查询改写后 rewritten != original
- **THEN** embed([rewritten, original]) 一次调用获取两个向量
- **AND** vectors[0] → 向量搜索，vectors[-1] → rerank 缓存匹配

#### Scenario: rewrite 禁用时退化
- **WHEN** rewritten == original (NoopRewriteProvider)
- **THEN** embed([query]) 一次调用，两个引用指向同一向量

### Requirement: Rerank 缓存基于原始 query embedding

Rerank 缓存匹配应从 `embed(改写后 query)` 改为 `embed(原始 query)`。

#### Scenario: 缓存匹配
- **WHEN** reranker.rerank() 执行
- **THEN** 缓存匹配使用 `cosine(embed(原始 query), cached_embed(原始))`
- **AND** 改写后相近但原始用词不同的 query 不会错误命中缓存

#### Scenario: 缓存存储
- **WHEN** LLM 重排完成并写入缓存
- **THEN** CacheEntry 存储 `original_query_embedding` 和 `original_query_text`
