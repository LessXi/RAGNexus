# Brainstorm Summary

- Change: production-readiness-and-bugfixes
- Date: 2026-06-29

## 确认的技术方案

### 组 A：Bug 修复（#1 httpx 泄漏、#2 log task 引用、#3 type:ignore、#8 缓存 key）

- **#1**: `aclose()` 方法 + lifespan finally 关闭 httpx 客户端
- **#2**: `set[Task]` 持有后台任务引用 + 回调自动移除
- **#3**: `cast(Any, repo_pool)` 替代 `# type: ignore[arg-type]`
- **#8**: 缓存 key 加入 `tuple(sorted(kb_ids))` 前缀

### 组 B：数据库能力（#4 Alembic、#5 log TTL）

- **#4**: alembic init → 基于 schema.sql 的初始迁移 → lifespan 启动检测告警
- **#5**: `prune(before)` 端口 → 启动时清理 → 24h 周期任务

### 组 C：新端点（#6 /health）

- **#6**: health_router.py（DB ping + Embedder HEAD，3s 超时，系统元信息）

### 组 D：清理与优化（#10 domain/errors 删除、#11 路由精简）

- **#10**: 删除文件 + 导入替换
- **#11**: 路由层构造精简 UploadResult

## 关键取舍与风险

- 缓存 key 变更 → 存量缓存自动失效
- Alembic 初始迁移手动编写（autogenerate 需模型定义）
- health endpoint 不检查可选 LLM Provider
- 无认证鉴权和多解析器支持（已明确排除）

## 测试策略

- 单元测试覆盖：httpx close 验证、缓存 key 变更、health router 响应
- 现有测试不回归：全量 pytest 运行

## Spec Patch

无。health-check 和 database-migration 的 spec 已在 OpenSpec 产物中。
