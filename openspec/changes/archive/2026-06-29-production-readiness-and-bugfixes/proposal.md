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
