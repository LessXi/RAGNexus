## 1. 资源泄漏修复

- [x] 1.1 在 OpenAICompatEmbedder 中添加 `async def close()` 关闭 httpx.AsyncClient
- [x] 1.2 在 OpenAICompatibleLLMProvider 中添加 `async def close()` 关闭 httpx.AsyncClient
- [x] 1.3 在 composition.py lifespan finally 块中添加 await embedder.close() 和 await llm_provider.close()

## 2. 后台任务引用修复

- [x] 2.1 为 RetrieveUseCase 添加 `_background_tasks: set[asyncio.Task]` 持有引用
- [x] 2.2 在 create_task 时加入 set 并在回调中自动移除
- [x] 2.3 验证 fire-and-forget 语义不变（不 await 后台任务）

## 3. 类型安全修复

- [x] 3.1 在 composition.py 中用 `cast(Any, repo_pool)` 替代 `# type: ignore[arg-type]`
- [x] 3.2 添加运行时类型断言确保 LoggedPool 行为正确

## 4. Alembic 数据库迁移

- [x] 4.1 安装 alembic 依赖并添加到 pyproject.toml
- [x] 4.2 运行 alembic init alembic 生成脚手架
- [x] 4.3 配置 alembic.ini 从 settings.PG_DSN 读取 sqlalchemy.url
- [x] 4.4 编写初始迁移脚本（基于 schema.sql 内容）
- [x] 4.5 在 composition.py lifespan 中添加迁移挂起检测告警

## 5. retrieve_logs TTL 清理

- [x] 5.1 在 PgRetrieveLogRepository 中添加 `async def prune(before: datetime) -> int` 方法
- [x] 5.2 在 lifespan 启动时执行一次清理（删除 >30 天日志）
- [x] 5.3 注册每 24h 执行的后台清理任务

## 6. 健康检查端点

- [x] 6.1 创建 adapters/http/health_router.py（DB 可达性 + Embedder API 检查 + 超时保护）
- [x] 6.2 在 composition.py 中注册 /health 路由
- [x] 6.3 添加系统元信息（版本、运行时间等）

## 7. 缓存 key 不含 kb_id 修复

- [x] 7.1 将 LLMRerankProvider 缓存 key 从 (embedding, chunk_id) 改为 (kb_ids, embedding, chunk_id)
- [x] 7.2 修复 clear_cache(kb_id) 按前缀匹配删除
- [x] 7.3 确保无存量缓存污染（新 key 自动失效旧缓存）

## 8. 移除 domain/errors.py

- [x] 8.1 搜索所有 `from ragnexus.domain.errors import ...` 替换为 `from ragnexus.core.errors import ...`
- [x] 8.2 删除 domain/errors.py 文件
- [x] 8.3 运行测试确认无导入断裂

## 9. UploadDocumentUseCase 路由优化

- [x] 9.1 在 upload_doc_router.py 中精简响应体（只返回 doc_id + chunk_count，不返回 chunks）
- [x] 9.2 运行相关测试确认无回归
