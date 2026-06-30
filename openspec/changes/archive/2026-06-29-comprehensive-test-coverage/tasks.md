# Tasks — comprehensive-test-coverage

> 19 项任务，分 4 个 Tier。每个任务完成后勾选。

## 1. 基础设施准备

- [x] 1.1 添加 dev 依赖：pytest-httpx>=0.23, pytest-asyncio 确认已安装
- [x] 1.2 pyproject.toml 添加 [tool.coverage.run] 配置（source + omit）
- [x] 1.3 E2E conftest.py DB 探活 skipif（DB 不可用时优雅跳过而非崩溃）

## 2. Tier 0 — 生死线（核心链路真实集成测试）

- [x] 2.1 编写 composition 生命周期集成测试：正常启动/关闭/迁移告警（`tests/integration/test_composition.py`）
- [x] 2.2 编写 RetrieveUseCase 真实集成测试：单 KB/多 KB/rerank 候选放大（`tests/integration/test_retrieve_full_chain.py` 重写为真实 DB）
- [x] 2.3 编写 UploadDocumentUseCase 真实集成测试：上传→检索全链路（`tests/integration/test_upload_full_chain.py`）
- [x] 2.4 编写 Alembic 迁移验证测试：upgrade head + downgrade -1（`tests/integration/test_alembic_migration.py`）

## 3. Tier 1 — 线上保障（失败模式覆盖）

- [x] 3.1 编写 embedder 降级测试：超时/重试耗尽/连接拒绝（补入 `tests/unit/adapters/test_embedder.py`）
- [x] 3.2 编写 LLMProvider 降级测试：429/连接拒绝（补入 `tests/unit/test_llm_provider.py`）
- [x] 3.3 编写 Semaphore 并发控制测试：验证 max_concurrency 限制和释放（补入 `tests/unit/adapters/test_embedder.py`）
- [x] 3.4 编写 close() 测试：Embedder 和 LLMProvider 正确关闭/重入安全（补入已有测试文件）
- [x] 3.5 编写生命周期错误恢复测试：Store 连接失败后资源清理（补入 `tests/integration/test_composition.py`，降级策略：若 mock 链路过长，改为真实 DB + 仅 mock Store）

## 4. Tier 2 — 技术债务清理

- [x] 4.1 重构 test_middleware.py fixture：MagicMock→AsyncMock 升级，恢复 4 个 skip 测试（降级策略：2 轮修不好则重写 lifespan mock 为可复用 helper 函数）
- [x] 4.2 补 frozenset 多 KB 缓存隔离测试（补入 `tests/unit/test_llm_rerank.py`）
- [x] 4.3 补 CacheInvalidatingUploadUseCase 测试：上传后 rerank/rewrite 缓存被清空（补入 `tests/unit/adapters/test_middleware.py`）

## 5. Tier 3 — E2E 补全

- [x] 5.1 E2E conftest 添加 pytest-httpx mock fixture（non_mocked_hosts 白名单避免拦截 TestClient）
- [x] 5.2 编写 /health 端点 E2E：正常 (200 + checks.db=ok) / 降级 (503 + checks.db=error)（补入 `tests/e2e/test_smoke.py`）
- [x] 5.3 编写 rewrite 启用全流程 E2E：mock LLM 返回改写结果 → 验证改写后检索（新文件 `tests/e2e/test_optimizations.py`）
- [x] 5.4 编写 rerank 启用全流程 E2E：mock LLM 返回重排结果 → 验证排序（同上）
- [x] 5.5 编写并发请求 E2E：5 并发检索无 500（补入 `tests/e2e/test_smoke.py`）
- [x] 5.6 编写外部服务降级 E2E：mock embedder 超时 / LLM 429 → 验证降级（补入 `tests/e2e/test_smoke.py`）
- [x] 5.7 编写 scripts/verify-production.sh 手工验收脚本

## 6. 验收

- [x] 6.1 全量单元+集成测试通过（无 skip，无 error）
- [x] 6.2 middleware 测试恢复：4 skip → pass（或按降级策略重写）
- [x] 6.3 E2E 测试通过：pytest tests/e2e/ -m "not real_api"
- [x] 6.4 覆盖率报告：pytest --cov=src/ragnexus --cov-report=term
- [x] 6.5 手工验收脚本执行：bash scripts/verify-production.sh（需 Docker + API key）
