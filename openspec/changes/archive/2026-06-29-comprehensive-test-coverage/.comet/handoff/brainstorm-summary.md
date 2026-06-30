# Brainstorm Summary

- Change: comprehensive-test-coverage
- Date: 2026-06-29

## 确认的技术方案

采用四层测试策略补全金字塔：

1. **Tier 0 集成测试**：真实 PostgreSQL + pgvector（Docker Compose test-db），外部 HTTP 用 pytest-httpx mock
2. **Tier 1 失败模式测试**：单元测试层 mock 异常（TimeoutException, HTTPStatusError），验证降级逻辑
3. **Tier 2 技术债务**：middleware fixture MagicMock→AsyncMock 升级，frozenset 缓存隔离，CacheInvalidatingUploadUseCase 覆盖
4. **Tier 3 E2E**：TestClient + pytest-httpx + non_mocked_hosts 白名单，mock 外部 HTTP，确定性可进 CI

手工验收脚本 scripts/verify-production.sh 不进 CI，部署前手动执行。

## 关键取舍与风险

- pytest-httpx 与 TestClient 冲突：用 non_mocked_hosts 排除 localhost
- Alembic env.py @lru_cache 陷阱：测试前 cache_clear() + 设 PG_DSN
- 连接池耗尽不可测：降级为 Semaphore 并发控制测试
- 生命周期错误恢复 mock 链路过长：降级策略为真实 DB + 仅 mock Store
- middleware fixture 可能仍修不好：2 轮降级为重写 helper 函数

## 测试策略

- 新增 4 个测试文件，重写 1 个（retrieve_full_chain Fake→真实 DB）
- 补入 8 个已有文件的新测试
- 新增 1 个手工验收脚本
- pyproject.toml 添加 coverage 配置

## Spec Patch

无。对抗性评审中已修正 specs/e2e-testing/spec.md 的 /health 返回值，已修正 specs/failure-mode-testing/spec.md 的连接池→Semaphore。
