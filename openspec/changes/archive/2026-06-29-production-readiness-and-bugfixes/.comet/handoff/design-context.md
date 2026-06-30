# Comet Design Handoff

- Change: production-readiness-and-bugfixes
- Phase: design
- Mode: compact
- Context hash: 24429985808322a2c6a81881678e23bb0d307d6a4d9d3190efdb0831d6555749

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/production-readiness-and-bugfixes/proposal.md

- Source: openspec/changes/production-readiness-and-bugfixes/proposal.md
- Lines: 1-32
- SHA256: bce30b53fe4823d6ac38b8beae43d7fc43e188aaf2854c0d2af32dabebea8387

```md
## Why

RAGNexus 当前的代码质量审查发现了 9 个需要修复的问题，涵盖资源泄漏、正确性风险、类型安全和生产就绪能力缺失。这些问题的根源是项目在初始开发阶段优先了功能完整度而忽略了运维健壮性。本轮修复旨在消除所有已知的正确性风险并补齐生产就绪的基础设施。

## What Changes

- 修复 httpx 客户端资源泄漏（`OpenAICompatEmbedder`、`OpenAICompatibleLLMProvider` 缺少 `aclose()`）
- 修复 `asyncio.create_task` 引用未持有导致的 GC 日志丢失风险
- 消除 `composition.py` 中两处 `# type: ignore[arg-type]`
- 集成 Alembic 数据库迁移框架，替代手动执行 schema.sql
- 为 `retrieve_logs` 表添加自动清理策略
- 新增 `/health` 健康检查端点
- 修复 `LLMRerankProvider` 缓存 key 不含 `kb_id` 导致跨 KB 打分不可比
- 移除 `domain/errors.py` 冗余向后兼容层
- 优化 `UploadDocumentUseCase` 路由层响应（不再序列化全量 Chunk）

## Capabilities

### New Capabilities
- `health-check`: 提供 `/health` HTTP 端点，返回数据库可达性、Embedder API 状态、系统运行时间等指标
- `database-migration`: 集成 Alembic 管理数据库 Schema 版本，生成初始迁移脚本

### Modified Capabilities
<!-- 全部修改为内部实现优化，不涉及公开 API 的验收标准变更，无需 delta spec -->

## Impact

- **代码**：`composition.py`、`retrieve_use_case.py`、`adapters/embedder/`、`adapters/llm/`、`adapters/rerank/`、`adapters/http/`
- **新增文件**：`alembic.ini`、`alembic/` 目录、`src/ragnexus/adapters/http/health_router.py`
- **依赖**：新增 `alembic` 依赖
- **数据库**：引入迁移管理，现有 schema 不变
- **API**：新增 GET `/health` 端点，现有端点响应格式不变
```

## openspec/changes/production-readiness-and-bugfixes/design.md

- Source: openspec/changes/production-readiness-and-bugfixes/design.md
- Lines: 1-106
- SHA256: 0649861553138753aacd9b58da6c10b0cd9206274bdf768bc4990d94217689ec

[TRUNCATED]

```md
## Context

RAGNexus 经过第一性原理审视后，发现 9 个确凿问题。其中 2 个为资源管理 bug（httpx 未关闭、log task 引用丢失），4 个为类型安全/正确性风险（type:ignore、缓存 key），3 个为生产就绪能力缺口（健康检查、数据库迁移、日志清理）。当前代码库无数据库迁移工具、无运维端点的设计状态。

## Goals / Non-Goals

**Goals:**
- 消除所有已知资源泄漏（httpx aclient aclose）
- 修复 asyncio log task 引用未持有的 GC 风险
- 消除 composition.py 中的类型安全缺口
- 修复 LLMRerankProvider 缓存 key 不含 kb_id 的正确性问题
- 集成 Alembic 数据库迁移框架
- 为 retrieve_logs 表添加 TTL 自动清理策略
- 新增 /health 健康检查端点
- 移除 domain/errors.py 冗余向后兼容层
- 优化 UploadDocumentUseCase 路由层响应

**Non-Goals:**
- 认证鉴权（后续独立 change）
- 多文档格式解析器（后续独立 change）
- 上传流水线并行化（性能优化，非本轮）
- API 版本管理策略

## Decisions

### D1: 修复 httpx 客户端泄漏 — `aclose()` 模式

**方案**：在 `OpenAICompatEmbedder` 和 `OpenAICompatibleLLMProvider` 中实现 `async def close()` 方法，关闭内部的 `httpx.AsyncClient`。在 `composition.py` 的 `lifespan` finally 块中调用 `await embedder.close()` 和 `await llm_provider.close()`。

**替代方案考虑**：使用 `httpx.AsyncClient` 的 context manager（`async with`）。拒绝原因：适配器实例在 lifespan 中创建后跨请求复用，context manager 会在 lifespan 退出前关闭客户端。

### D2: 修复 log task 引用丢失 — `BackgroundTaskManager`

**方案**：在 `RetrieveUseCase` 中引入一个 `set[asyncio.Task]` 持有所有后台任务引用。任务完成时自动移除引用。替代在多个 Use Case 中重复该模式。

**替代方案考虑**：
- 使用 `asyncio.TaskGroup`（Python 3.11+ 可用，但会阻塞等待所有后台任务完成，不符合 fire-and-forget 语义）
- 单行 `asyncio.ensure_future` 包装。拒绝原因：同样需要持有引用

**选型理由**：`set` 持有 + 回调清理是最轻量的 fire-and-forget 模式，不改变日志的异步语义，不阻塞响应返回。

### D3: 消除 `# type: ignore[arg-type]` — `LoggedPool` 实现 Protocol

**方案**：让 `LoggedPool` 实现 `asyncpg.Pool` 的完整 Protocol（`acquire`、`release`、`close` 等方法签名对齐），或改为用 `cast()` 明确表达"这里类型转换是设计意图"。

**决策**：优先 `cast()` — `LoggedPool` 不是 asyncpg.Pool 的真正实现，只是代理。`cast()` 明确告诉类型检查器和读者"这就是设计意图"。改动最小，风险最低。

### D4: Alembic 集成

**方案**：在项目根目录初始化 Alembic，生成 `alembic.ini` 和 `alembic/` 目录。创建初始迁移脚本（基于当前 schema.sql 的自动迁移）。在 `composition.py` 的 lifespan 启动时检测未运行迁移并告警。

**配置**：alembic.ini 的 `sqlalchemy.url` 从 `settings.PG_DSN` 读取。env.py 的 `target_metadata` 使用 SQLAlchemy Core 的 `MetaData` 对象（不引入 ORM）。

### D5: retrieve_logs TTL 清理

**方案**：在 `PgRetrieveLogRepository` 中新增 `async def prune(before: datetime) -> int` 方法。在 `composition.py` 的 lifespan 中注册一个周期任务（每 24h 执行一次），删除 `created_at < NOW() - INTERVAL '30 days'` 的记录。或者在启动时一次性清理（更简单，零运行时开销）。

**简化决策**：启动时一次性清理 + 周期性清理。启动时清理超过 30 天的旧日志。然后作为 lifespan 后台任务每 24h 执行一次。

### D6: 缓存 key 包含 kb_ids

**方案**：`LLMRerankProvider.rerank` 方法的缓存 key 从 `(query_embedding_tuple, chunk_id)` 改为 `(tuple(sorted(kb_ids)), query_embedding_tuple, chunk_id)`。同时迁移 `clear_cache(kb_id)` 的逻辑：从按 kb_id 逐条删除改为按 kb_id 前缀匹配。

**关键注意**：重新计算缓存 key 后，存量缓存自动失效（新 key 不会命中旧缓存），无需手动清除。

### D7: `/health` 端点设计

**方案**：新建 `adapters/http/health_router.py`，创建 `create_router(store, embedder)` 函数。检查项：DB 连接池可达性（`pool.fetchval("SELECT 1")`）、Embedder API 端点（HEAD 请求）。超时保护 3 秒/项。

**不检查 LLM Provider**：Rerank 和 Rewrite 是可选的，任何单项 LLM 不可用不应影响存活状态。

**路径**：在路由中实现，而非 middleware。路由不经过 lifespan 依赖注入的外部数据库状态，通过 `app.state.store` 和 `app.state.embedder` 访问。

### D8: 移除 domain/errors.py

**方案**：删除 `domain/errors.py`。将 `domain/errors.py` 的所有导入引用替换为直接导入 `core/errors`。`DomainError` 别名不再需要——所有层已直接使用 `AppError`。

### D9: UploadDocumentUseCase 路由优化

**方案**：`upload_doc_router.py` 中，路由函数调用 `use_case.execute(...)` 后，不序列化全量 `UploadResult.chunks` 列表。当前路由只取 `chunk_count`，但 Use Case 返回了包含所有 Chunk 对象的完整结果。
```

Full source: openspec/changes/production-readiness-and-bugfixes/design.md

## openspec/changes/production-readiness-and-bugfixes/tasks.md

- Source: openspec/changes/production-readiness-and-bugfixes/tasks.md
- Lines: 1-53
- SHA256: e03c99c12f6a492acc691c2e47c006cd246c5adc4935d2bb7c3772f3dcf84992

```md
## 1. 资源泄漏修复

- [ ] 1.1 在 OpenAICompatEmbedder 中添加 `async def close()` 关闭 httpx.AsyncClient
- [ ] 1.2 在 OpenAICompatibleLLMProvider 中添加 `async def close()` 关闭 httpx.AsyncClient
- [ ] 1.3 在 composition.py lifespan finally 块中添加 await embedder.close() 和 await llm_provider.close()

## 2. 后台任务引用修复

- [ ] 2.1 为 RetrieveUseCase 添加 `_background_tasks: set[asyncio.Task]` 持有引用
- [ ] 2.2 在 create_task 时加入 set 并在回调中自动移除
- [ ] 2.3 验证 fire-and-forget 语义不变（不 await 后台任务）

## 3. 类型安全修复

- [ ] 3.1 在 composition.py 中用 `cast(Any, repo_pool)` 替代 `# type: ignore[arg-type]`
- [ ] 3.2 添加运行时类型断言确保 LoggedPool 行为正确

## 4. Alembic 数据库迁移

- [ ] 4.1 安装 alembic 依赖并添加到 pyproject.toml
- [ ] 4.2 运行 alembic init alembic 生成脚手架
- [ ] 4.3 配置 alembic.ini 从 settings.PG_DSN 读取 sqlalchemy.url
- [ ] 4.4 编写初始迁移脚本（基于 schema.sql 内容）
- [ ] 4.5 在 composition.py lifespan 中添加迁移挂起检测告警

## 5. retrieve_logs TTL 清理

- [ ] 5.1 在 PgRetrieveLogRepository 中添加 `async def prune(before: datetime) -> int` 方法
- [ ] 5.2 在 lifespan 启动时执行一次清理（删除 >30 天日志）
- [ ] 5.3 注册每 24h 执行的后台清理任务

## 6. 健康检查端点

- [ ] 6.1 创建 adapters/http/health_router.py（DB 可达性 + Embedder API 检查 + 超时保护）
- [ ] 6.2 在 composition.py 中注册 /health 路由
- [ ] 6.3 添加系统元信息（版本、运行时间等）

## 7. 缓存 key 不含 kb_id 修复

- [ ] 7.1 将 LLMRerankProvider 缓存 key 从 (embedding, chunk_id) 改为 (kb_ids, embedding, chunk_id)
- [ ] 7.2 修复 clear_cache(kb_id) 按前缀匹配删除
- [ ] 7.3 确保无存量缓存污染（新 key 自动失效旧缓存）

## 8. 移除 domain/errors.py

- [ ] 8.1 搜索所有 `from ragnexus.domain.errors import ...` 替换为 `from ragnexus.core.errors import ...`
- [ ] 8.2 删除 domain/errors.py 文件
- [ ] 8.3 运行测试确认无导入断裂

## 9. UploadDocumentUseCase 路由优化

- [ ] 9.1 在 upload_doc_router.py 中精简响应体（只返回 doc_id + chunk_count，不返回 chunks）
- [ ] 9.2 运行相关测试确认无回归
```

## openspec/changes/production-readiness-and-bugfixes/specs/database-migration/spec.md

- Source: openspec/changes/production-readiness-and-bugfixes/specs/database-migration/spec.md
- Lines: 1-27
- SHA256: 649cfbc533673b0eb650fc5a5f6c35147b19a11f1919866b8590c3ac585b7de1

```md
## ADDED Requirements

### Requirement: 数据库迁移管理

使用 Alembic 管理数据库 Schema 的版本化迁移，替代手动执行 schema.sql。

#### Scenario: 初始迁移
- **WHEN** 运行 `alembic upgrade head`
- **THEN** 数据库中创建 `alembic_version` 表，所有 schema.sql 中的表（knowledge_bases、documents、chunks、retrieve_logs）以及 pgvector extension、HNSW 索引被创建

#### Scenario: 迁移可回滚
- **WHEN** 运行 `alembic downgrade -1`
- **THEN** schema 回退到上一个版本，数据不丢失（降级脚本不删除用户数据表，仅撤销结构性变更）

#### Scenario: 自动迁移
- **WHEN** 应用启动时检测到未执行的迁移
- **THEN** 应用打印警告日志 `WARNING: N pending migration(s). Run 'alembic upgrade head' before deploying`

### Requirement: 迁移脚本生成

#### Scenario: 自动生成
- **WHEN** 开发者修改了模型定义后运行 `alembic revision --autogenerate -m "<描述>"`
- **THEN** 生成包含正确 UPGRADE 和 DOWNGRADE 操作的迁移脚本

## REMOVED Requirements

<!-- 无 -->
```

## openspec/changes/production-readiness-and-bugfixes/specs/health-check/spec.md

- Source: openspec/changes/production-readiness-and-bugfixes/specs/health-check/spec.md
- Lines: 1-33
- SHA256: 3e74ae285da73ef538b4e0bebd602b1c2c3fe18ac237aac7b26d91694b820110

```md
## ADDED Requirements

### Requirement: 健康检查端点

系统提供一个 GET /health 端点，用于负载均衡和容器编排的存活探针。

#### Scenario: 正常响应
- **WHEN** 数据库连接池可达且 Embedder API 端点可响应
- **THEN** 返回 HTTP 200 状态码，JSON body 包含 `{"status": "ok", "timestamp": "<ISO8601>", "checks": {"database": "ok", "embedder": "ok"}}`

#### Scenario: 数据库不可达
- **WHEN** 数据库连接池 acquire 超时或返回连接错误
- **THEN** 返回 HTTP 503 状态码，JSON body 包含 `{"status": "degraded", "checks": {"database": "error", "embedder": "<实际状态>"}}`

#### Scenario: Embedder API 不可达
- **WHEN** Embedder API 端点连接超时或返回非 2xx
- **THEN** 返回 HTTP 503 状态码，JSON body 包含 `{"status": "degraded", "checks": {"database": "ok", "embedder": "error"}}`

#### Scenario: 超时保护
- **WHEN** 任一健康检查单项超过 3 秒未返回
- **THEN** 该单项标记为 "timeout"，不阻塞整体响应

### Requirement: 系统元信息披露

健康检查端点同时暴露最小系统元信息，便于运维快速诊断。

#### Scenario: 基本信息
- **WHEN** 请求 GET /health
- **THEN** 响应中包含 `"version": "<pyproject.toml version>"`、`"uptime_seconds": <进程启动到现在的秒数>`、`"python_version": "<sys.version>"`

## REMOVED Requirements

<!-- 无 -->
```

