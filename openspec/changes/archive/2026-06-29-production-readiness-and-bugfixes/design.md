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

**方案**：在路由层用 `UploadResult(doc_id=result.doc_id, chunk_count=result.chunk_count, chunks=[])` 构造精简响应。不改 Use Case 签名（Use Case 完整性大于路由偏好）。

### D10: 生命周期管理

**lifespan 启动顺序**（修改后）：
1. 创建向量存储连接池
2. 创建共享仓库连接池
3. 执行数据库迁移检测
4. EMBED_DIM 维度校验
5. 实例化适配器（embedder、llm_provider 等）
6. 注册后台清理任务（retrieve_logs TTL）
7. 实例化 Use Cases
8. 注册路由（含 /health）
9. yield（运行）
10. finally: await embedder.close()、await llm_provider.close()、关闭连接池

## Risks / Trade-offs

| 风险 | 级别 | 缓解措施 |
|------|------|---------|
| Alembic autogenerate 依赖 SQLAlchemy 模型定义 | 低 | 初始迁移手动编写，后续通过 autogenerate 增量管理 |
| 后台清理任务可能引入未捕获异常 | 低 | 用 try/except 包裹，异常仅 DEBUG 日志 |
| 缓存 key 改变后热缓存丢失 | 低 | 仅影响首次请求（延迟增加几百毫秒），且所有现有缓存会在上传时被清空 |
| health_router 依赖 app.state | 中 | lifespan 中显式注入，启动时未注册则返回 503 |
| LoggedPool cast() 掩盖真实类型 | 低 | 添加类型注释和运行时断言兜底 |
