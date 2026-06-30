# Brainstorm Summary

- Change: ragnexus-skeleton
- Date: 2026-06-23

## 确认的技术方案

1. **Embedder 批次失败**：全有或全无。asyncio.gather 任一批次异常 → 整体事务回滚，500/502 返回客户端。客户端重试安全（doc_exists 幂等检查）。

2. **EMBED_DIM 失配检测**：启动时 lifespan 查询 `pg_attribute.atttypmod` 获取 `chunks.embedding` 列实际维度，与 `cfg.EMBED_DIM` 对比。失配 → `ConfigError`(code=1600)。新增 `ConfigError(DomainError)` 异常类。

3. **并发控制**：不做应用级全局 upload semaphore。骨架阶段信任 uvicorn worker + asyncpg pool（max=10）自然限流。生产环境建议 `--workers 4` + 调整 `EMBED_MAX_CONCURRENCY` 每 worker。

4. **测试策略**：
   - 集成测试：独立 `ragnexus_test` DB + pytest session-scoped fixture 建表/拆表、teardown 清理
   - Docker Compose：独立 `docker-compose.test.yml` 管理测试 PG + 自动初始化

## 关键取舍与风险

- 全有或全无回滚浪费 flaky 上游时已算好的 embedding
- 幂等性完全依赖 `doc_exists` 早期检查（绕过 → 409 而非静默重复）
- 无全局并发控制 → 单 worker 大量 upload 可能压爆 embedder 上游（依赖重试兜底）
- EMBED_DIM 改后必须重跑 schema.sql（启动检测会报 ConfigError 而非静默失败）

## 测试策略

- 单元测试：mock 全部端口（pytest + pytest-asyncio）
- 集成测试：独立 test-db（docker-compose.test.yml），真实 pgvector + mock embedder
- E2E：`test_smoke.py` 端到端验证 3 个 API
- Fixture 生命周期：session-scoped（建表一次，测试间事务隔离）

## Spec Patch

- `domain/errors.py`：新增 `ConfigError(DomainError)` code=1600, http_status=500
- `composition.py` lifespan：EMBED_DIM 维度失配检测（查询 pg_attribute）
- `docker-compose.test.yml`：新增测试环境编排
- 设计文档显式记录 all-or-nothing 语义 + idempotent retry + 并发模型
