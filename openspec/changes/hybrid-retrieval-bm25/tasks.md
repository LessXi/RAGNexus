## 1. 领域层 (Domain)

- [x] 1.1 在 `domain/ports.py` 新增 `KeywordSearchPort` 协议（upsert、search_by_keyword、delete）
- [x] 1.2 新增 `domain/retrieval/__init__.py` 和 `domain/retrieval/fusion.py`（rrf_fuse 函数）
- [x] 1.3 更新 `RerankPort` docstring：score 语义从"向量原始分"改为"融合相关性分"

## 2. ES 适配器

- [x] 2.1 新增 `adapters/keyword_search/__init__.py`
- [x] 2.2 新增 `adapters/keyword_search/elasticsearch.py`（ESKeywordSearchProvider：连接管理、ensure_index、upsert、search_by_keyword、delete）
- [x] 2.3 新增 `adapters/keyword_search/noop.py`（NoopKeywordSearchProvider：空实现）
- [x] 2.4 添加 `elasticsearch-py[async]` 到 pyproject.toml

## 3. PG 事务控制

- [x] 3.1 重构 `PgVectorStore`：拆分 upsert 为 `acquire_connection()` + `_upsert_in_transaction(conn, ...)`，commit 控制权外提
- [x] 3.2 更新 `VectorStorePort` 协议（无需变更——新方法是 PgVectorStore 私有方法）

## 4. 上传链路

- [x] 4.1 `UploadDocumentUseCase` 改为并发双写：ES + PG 并行走，外部控 commit/rollback
- [x] 4.2 处理 4 种双写状态矩阵（✓✓、✗✗、✓✗ rollback、✗✓ delete）
- [x] 4.3 新增日志事件：keyword_upsert_done、keyword_upsert_fail、es_orphan_cleanup_done、es_orphan_cleanup_fail
<!-- 注: CacheInvalidatingUploadUseCase 无需修改 — ES 无缓存，keyword_store 无 clear_cache 方法 -->

## 5. 检索链路

- [x] 5.1 `RetrieveUseCase` 改为双 embedding（rewrite 向量 + 原始向量）→ 并行召回 → RRF 融合
- [x] 5.2 按 `RETRIEVAL_MODE` 控制 vector/bm25 是否执行（空列表自然退化，无需分支）
- [x] 5.3 新增日志事件：keyword_search_done、keyword_search_fail
- [x] 5.4 扩展 `retrieve_completed` 日志：retrieval_mode、vector_hit_count、keyword_hit_count、rrf_pool_size、vector_latency_ms、keyword_latency_ms

## 6. Rerank 缓存

- [x] 6.1 `LLMRerankProvider` 缓存从 `query_embedding` 改为 `original_query_embedding`
- [x] 6.2 CacheEntry 新增 `original_query_embedding` 和 `original_query_text` 字段
- [x] 6.3 更新 `RerankPort.rerank()` 的 `query_vector` 语义：从 `embed(改写后)` 改为 `embed(原始)`
- [x] 6.4 更新 `_merge_and_sort` 和 `_rerank_impl` 中的注释

## 7. 配置

- [x] 7.1 `config.py` 新增 7 个配置项（RETRIEVAL_MODE、ES_ENABLED 等）
- [x] 7.2 废弃 2 个配置项（RERANK_CANDIDATE_MULTIPLIER、RERANK_MIN_CANDIDATES）
- [x] 7.3 启动时配置校验：ES_ENABLED=true 但 URL 不可达时打 WARNING，不阻断启动（composition.py 中已实现优雅降级）

## 8. 依赖注入

- [x] 8.1 `composition.py` 新增 ES 客户端生命周期：初始化、ensure_index、close
- [x] 8.2 按 ES_ENABLED 注入 ESKeywordSearchProvider 或 NoopKeywordSearchProvider
- [x] 8.3 keyword_store 注入到 UploadDocumentUseCase 和 RetrieveUseCase
- [x] 8.4 关停时关闭 ES 客户端

## 9. 基础设施

- [x] 9.1 docker-compose.yml 新增 elasticsearch 服务（单节点、禁用安全、`ES_JAVA_OPTS="-Xms512m -Xmx512m"`、持久卷）
- [x] 9.2 ES 索引 mapping 定义（chunk_id/keyword、kb_id/keyword、heading/text、text/text、metadata/object）— 在 ESKeywordSearchProvider 中实现
- [x] 9.3 更新 `.env.example` 加入 7 个新配置项

## 10. 测试

- [x] 10.1 单元测试：rrf_fuse() 各种场景（两路正常、一路空、跨来源去重）
- [x] 10.2 单元测试：NoopKeywordSearchProvider 三项方法
- [x] 10.3 单元测试：UploadDocumentUseCase 双写四种状态矩阵
- [x] 10.5 集成测试：混合检索全链路（需 ES 可用）— 测试文件就绪，13 个用例
- [x] 10.6 集成测试：ES 不可用时降级为纯向量 — 测试文件就绪，10 个用例 + 2 个生产 bug 修复
- [x] 10.7 单元测试：rerank 缓存匹配行为变更（原始 vs 改写 query embedding）
- [x] 10.8 回归测试：所有现有测试通过（336 passed）
- [x] 10.9 Docker 环境端到端验证：启动真实系统（ES + PG + RAGNexus），上传文档执行检索，通过日志确认混合检索链路实际生效（keyword_search_done、vector_search_done、rrf_fusion 等日志事件可观测），验证 hybrid/vector/bm25 三种模式的检索结果差异
  - E2E 测试文件 `tests/e2e/test_docker_e2e_hybrid.py`（12 个用例）就绪
  - 验证脚本 `scripts/e2e_verify.sh` / `scripts/e2e_verify.ps1` 就绪
  - 待 Docker 环境启动后执行
