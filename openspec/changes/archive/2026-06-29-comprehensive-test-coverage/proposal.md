## Why

RAGNexus 当前 319 个单元测试全部通过，但测试金字塔严重倒置——81% 的源码只有 mock 覆盖，核心业务链路（上传→解析→分块→向量化→存储→检索→重排）从未在真实环境中完整验证。新增功能（/health 端点、TTL 清理、close() 资源释放、Alembic 迁移、frozenset 缓存）几乎零测试覆盖。此外 E2E 测试在数据库不可用时崩溃而非优雅跳过，CI 无法执行。

简单说：**319 个测试全绿，但没人知道线上能不能跑。**

## What Changes

### 新增（按 Tier 分层）

**Tier 0 — 生死线（核心链路真实集成测试，上线前必备）**
- composition.py 集成测试：启动/关闭全生命周期（DB 连接、维度检测、迁移告警、TTL 清理、资源关闭顺序）
- RetrieveUseCase 真实集成测试：embed→search→rerank→log 全链路（真实 PostgreSQL + pgvector，mock 外部 HTTP）
- UploadDocumentUseCase 真实集成测试：parse→chunk→embed→store 全链路（同上）
- Alembic upgrade/downgrade 验证测试：迁移脚本在真实 DB 上可执行可回滚

**Tier 1 — 线上保障（失败模式覆盖）**
- 外部服务降级测试：embedder/LLM 超时、429 限流、连接拒绝时的降级行为
- 连接池耗尽测试：并发压力下 backpressure 不会 silent hang
- 生命周期错误恢复测试：启动阶段某步失败后资源清理正确性
- close() 测试：embedder/LLM HTTP client 正确关闭、无泄漏、重入安全

**Tier 2 — 技术债务清理**
- middleware fixture 重构：4 个 skip 测试恢复（MagicMock → AsyncMock 升级）
- candidate_k=0 边界测试：防御性配置边界验证
- E2E DB 探活 skipif：数据库不可用时优雅跳过而非崩溃
- coverage 配置：pyproject.toml 添加 `[tool.coverage.run]`

**Tier 3 — E2E 补全 + 手工验收**
- 引入 pytest-httpx：确定性 mock 外部 HTTP，E2E 可进 CI
- /health 端点 E2E：正常/降级/超时
- rewrite 启用全流程 E2E：mock LLM 返回改写结果 → 验证改写后检索正确
- rerank 启用全流程 E2E：mock LLM 返回重排结果 → 验证重排后排序正确
- 并发请求 E2E：5 并发请求连接池不炸
- 外部服务降级 E2E：mock 超时/429/连接拒绝 → 验证 HTTP 层降级行为
- `scripts/verify-production.sh`：手工验收脚本（启动 Docker → 迁移 → 真实 embedder/LLM 全链路验证 → 覆盖率报告），不进 CI

### 不变

- 不修改业务逻辑代码（除非发现 bug）
- 不新增功能
- 认证鉴权（#7）和多解析器（#9）不在本次范围

## Capabilities

### New Capabilities

- `integration-testing`: 真实 PostgreSQL + pgvector 集成测试基础设施，覆盖 composition 生命周期和核心业务链路
- `e2e-testing`: 确定性 E2E 测试框架（pytest-httpx mock 外部 HTTP），覆盖 HTTP 全栈行为
- `failure-mode-testing`: 外部服务故障注入和降级行为验证
- `coverage-config`: pytest-cov 配置和覆盖率报告
- `manual-verification`: 手工验收脚本，真实环境全链路一次性验证

### Modified Capabilities

无。本次不修改任何已有 spec 的 REQUIREMENTS，纯补测试覆盖。
