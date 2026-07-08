## Context

RAGNexus 当前 upload 流程在单个 HTTP 连接内同步执行全部索引步骤（解析→分块→Embedding→双写 pgvector+ES），大文档导致超时。同时知识库和文档缺少生命周期管理——只能创建不能修改删除。改造后 upload 秒回 PROCESSING，Celery Worker 后台异步索引；补齐知识库和文档的 CRUD 运维接口。

**架构约束**：Clean Architecture (domain→application→adapters)，纯 async 全链路，Port-Adapter 模式，Docker Compose 部署。

## Goals / Non-Goals

**Goals:**
- upload 接口 <1s 返回，索引由 Celery Worker 后台异步执行
- 文档三态状态机：PROCESSING → SUCCESS | FAILED，支持重试、超时恢复
- 知识库 CRUD：详情查询（含完整 settings）、更新（name/description/settings）、级联删除
- 文档 CRUD：状态查询、删除（级联清理 pgvector+ES）、失败重试
- 前端适配异步体验：状态轮询、操作入口

**Non-Goals:**
- 不改变检索/Embedding/分块算法
- 不改变现有双写事务逻辑
- 不新增用户认证体系
- 不修改 admin 检索页

## Decisions

### D1: Celery + Redis 作为任务队列

**选 Celery 而非 arq/内置 asyncio**。Celery 是业界标准，监控/重试/超时/结果存储开箱即用。RAGNexus 全链路 async 的索引逻辑通过 `asyncio.run()` 桥接。

**asyncpg Pool 隔离**：`asyncio.run()` 创建独立 event loop，不可跨调用复用 Pool。每个 Celery task 在 `asyncio.run()` 回调内部临时创建 asyncpg Pool（`min_size=1, max_size=3`），用完即关。索引任务是低频操作（非每秒数百次），Pool 创建开销（<50ms）可忽略。或者使用 `celery.signals.worker_process_init` 在每个 Worker 子进程启动时创建持久的 event loop + Pool（但增加代码复杂度，不推荐）。

**Celery ack 策略**：配置 `task_acks_late=True` 确保 Worker 完成索引后才 ACK。Worker 中途崩溃时任务自动重新投递，不依赖 30 分钟 timeout monitor。
### D2: 独立 DocumentPort + PgDocumentRepository

当前 `PgKnowledgeBaseRepository` 同时管理 KB 和文档操作，职责过重。抽取 `DocumentPort` Protocol，`PgDocumentRepository` 实现，解除耦合。`KnowledgeBasePort` 扩展 `update`/`delete` 方法。

### D3: UploadUseCase 拆分为建记录 + 投递任务

现有 `UploadDocumentUseCase.execute()` 拆为两步：
1. API 侧：校验 → 建 documents 行（`content` 落库，`status=PROCESSING`）→ `task.delay(doc_id)` → 返回
2. Worker 侧：`IndexingService.execute(doc_id)` → 读 content → 复用现有 parser/chunker/embedder/store → 更新 status

**索引核心逻辑零改动**——parse/chunk/embed/dual_write 代码不变，只改变入口参数（从 `file_content bytes` 变为 `doc_id` 读 DB）和调用时机。

### D4: 整数状态枚举 + 状态转换矩阵

`DocStatus` IntEnum：SUCCESS=1, PROCESSING=2, FAILED=3。状态转换：

```
upload → PROCESSING → Worker 完成 → SUCCESS
                   → Worker 失败 → FAILED
reindex          → PROCESSING (仅从 FAILED)
```

### D5: 统一 purge_document_chunks 方法

删文档、删知识库、reindex 三处共用的双存储清理逻辑，抽取为 `purge_document_chunks(doc_id)`，确保 ES 不被遗漏导致脏数据。

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| `asyncio.run()` 创建独立 event loop → asyncpg Pool 不可跨调用复用 | 每个 task 内部临时创建 Pool（min_size=1, max_size=3），用完即关。索引低频，开销可忽略 |
| Worker 崩溃 → 任务丢失、文档永久 PROCESSING | Celery `task_acks_late=True` 确保 Worker 完成后才 ACK，崩溃自动重新投递；Celery beat 每 5 分钟扫描超时文档标记 FAILED 作为兜底 |
| 删库时 Worker 正在索引该库文档 | 删库前 `has_processing(kb_id)` 检查，拒绝删除 |
| ES/PG 双写一致性问题 | 复用现有双写事务逻辑（双成功才 commit） |
| Celery Worker 独立进程，event loop 与 FastAPI/uvicorn 完全隔离 | 通过 `asyncio.run()` 创建独立 event loop，两个进程的 asyncpg Pool 互不干扰。在代码注释中明确说明隔离机制，避免维护者困惑 |
