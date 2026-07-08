# Brainstorm Summary

- Change: async-indexing-lifecycle
- Date: 2026-07-05

## 确认的技术方案

| 层面 | 决策 |
|------|------|
| 任务队列 | Celery + Redis，task 内 asyncio.run() 桥接 async 索引 |
| 文档仓库 | 独立 DocumentPort + PgDocumentRepository |
| Upload 拆分 | API 建记录+投递 → Worker IndexingService 执行（索引代码零改动） |
| 状态机 | DocStatus IntEnum: SUCCESS=1, PROCESSING=2, FAILED=3 |
| 副作用编排 | Celery task 编排：索引→清缓存→词表同步，IndexingService 纯函数 |
| DI 工厂 | 从 composition.py 抽取 build_indexing_services(cfg) 共享工厂 |
| 双写清理 | 统一 purge_document_chunks，删文档/删库/reindex 复用 |
| 超时恢复 | Celery beat 定时扫描 PROCESSING>30min → FAILED |

## 关键取舍与风险

- Celery 同步模型 vs RAGNexus async 架构：接受 asyncio.run() 桥接，换取成熟生态
- composition.py 主动重构抽取 DI 工厂，避免 API/Worker 两处维护
- 删库竞态用 has_processing() 检查拒绝，不加分布式锁（简单优先）

## 测试策略

- 单元：IndexingService、DocumentRepository、KnowledgeBaseRepository
- 集成：异步上传→检索命中、ES 不可用→reindex→SUCCESS、KB CRUD 全覆盖
- E2E：PROCESSING 状态拒绝、跨租户隔离

## Spec Patch

无 — 三个 delta spec 已含完整验收场景
