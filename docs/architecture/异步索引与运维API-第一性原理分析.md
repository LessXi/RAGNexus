# 异步索引与运维 API — 第一性原理分析

> 基于三篇飞书文档的端到端需求，从 RAGNexus 架构第一性原则出发设计融入方案。
> **约束：优先重构，不考虑向后兼容。任务队列：Celery。**

## 一、根问题识别

三篇文档是一条**因果链**，不是三个独立需求：

```
大文档 HTTP 超时
  → 索引必须异步化
    → 文档需要状态机（PROCESSING/SUCCESS/FAILED）
      → 需要文档生命周期管理（查状态、删、重试）
        → 知识库也需要生命周期管理（查、改、删）
          → 前端适配异步体验（轮询、状态展示）
```

**根问题只有一个：同步 I/O 密集任务阻塞了 HTTP 连接。** 其他所有需求都是连锁反应。

## 二、当前架构约束

| 原则 | 体现 |
|------|------|
| Clean Architecture | domain → application → adapters |
| 纯 async | 全链路 async/await |
| Port-Adapter | Protocol 定义契约 |
| Docker Compose | 单一 compose 管理所有服务 |
| 渐进式启用 | 环境变量开关（AUTH_ENABLED, ES_ENABLED 等） |

### 现实发现

- `schema.sql` 与代码不同步：`knowledge_bases` 代码已用 `tenant_id/description/settings`（JSONB），Schema 未更新
- `documents` 表缺少 `status/content/error_message` 列
- 没有独立的 `DocumentPort`，文档操作嵌在 `PgKnowledgeBaseRepository` 中
- `tree` 的 `status` 字段写死为 `"completed"`，从未真正使用
- upload 去重基于 `SHA256(file_content)`，异步化后 content 需落库供 Worker 读

## 三、核心设计决策

### 决策 1：任务队列 — Celery + Redis

选 Celery，不选 arq 或内置 asyncio Task。理由：

- **团队决定**，不做架构争论
- Celery 是业界标准，监控/重试/超时/结果存储开箱即用
- RAGNexus 虽全链路 async，但 Celery task 内部用 `asyncio.run()` 桥接，一次包装即可

**兼容策略**：Celery task 定义是同步函数签名，但索引逻辑全是 async（asyncpg、aiohttp 等），需要在 task 函数内部用 `asyncio.run()` 包装：

```python
@celery_app.task(bind=True, max_retries=2, default_retry_delay=10)
def index_document_task(self, document_id: str):
    """Celery task — 内部桥接 async IndexingService。"""
    asyncio.run(_do_index(document_id))
```

```yaml
# docker-compose.yml 新增
redis:
  image: redis:7-alpine
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]

worker:
  build: .
  command: celery -A src.ragnexus.celery_app worker --loglevel=info
  depends_on:
    redis:
      condition: service_healthy
    db:
      condition: service_healthy
  env_file: .env
```

```python
# Settings 新增
CELERY_BROKER_URL: str = "redis://localhost:6379/0"
CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
```

### 决策 2：独立 DocumentPort

当前 `PgKnowledgeBaseRepository` 管了 KB + 文档 + tree，职责过重。**抽取 `DocumentPort`**：

```python
class DocumentPort(Protocol):
    async def get(self, doc_id: str) -> Document | None: ...
    async def create(self, doc: Document) -> Document: ...
    async def update_status(self, doc_id: str, *,
        status: DocStatus, error_message: str | None,
        chunk_count: int) -> None: ...
    async def delete(self, doc_id: str) -> None: ...
    async def list_by_kb(self, kb_id: str) -> list[Document]: ...
    async def has_processing(self, kb_id: str) -> bool: ...
```

`PgKnowledgeBaseRepository` 不再管文档，专注 KB CRUD + tree 查询。

### 决策 3：upload 流程拆分

```
（API 侧 — HTTP 连接内，<1s）
  UploadUseCase.execute()
    ├── 校验（扩展名、大小、KB 归属）
    ├── doc_id = SHA256(content)[:16]
    ├── 写 documents 行（content 落库，status=PROCESSING）
    ├── index_document_task.delay(doc_id)
    └── 返回 {doc_id, status: PROCESSING, chunk_count: 0}

（Worker 侧 — 后台异步，不计入 HTTP 耗时）
  IndexingService.execute(doc_id)
    ├── 读 document.content
    ├── 解析 → 分块 → Embedding → 双写(pgvector+ES)
    ├── 更新 status=SUCCESS + chunk_count
    └── 失败 → status=FAILED + error_message
```

**索引代码零改动**：解析/分块/Embedding/双写的现有代码一行不改，只改变调用方和调用时机。

### 决策 4：状态机

```python
class DocStatus(IntEnum):
    SUCCESS = 1
    PROCESSING = 2
    FAILED = 3
```

| 操作 | PROCESSING | SUCCESS | FAILED |
|------|:---:|:---:|:---:|
| DELETE 文档 | 拒绝 | 允许 | 允许 |
| POST reindex | 拒绝 | 拒绝 | 允许 |
| DELETE 知识库（库下有 PROCESSING 文档） | 拒绝 | — | — |

Worker 崩溃恢复：PROCESSING 超过 30min → 定时任务标记 FAILED。

### 决策 5：双存储清理统一方法

删文档、删知识库、reindex 三处都要清理 pgvector（向量）+ Elasticsearch（关键词索引），抽取为统一方法避免遗漏 ES 清理导致脏数据：

```python
async def purge_document_chunks(
    doc_id: str,
    store: VectorStorePort,
    keyword_store: KeywordSearchPort | None,
):
    """清理文档的所有 chunk：PG 向量 + ES 关键词索引。"""
    # PG: CASCADE 自动清理 / 显式 DELETE
    # ES: delete_by_document_id
```

## 四、实施路线图

### Phase 1：基础设施（0.5 天）

- [ ] docker-compose.yml 加 Redis + Celery worker 服务
- [ ] pyproject.toml 加 `celery[redis]>=5.4.0` + `redis>=5.0.0`
- [ ] Settings 加 `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`
- [ ] Alembic migration: `documents` 表加 `status INT`, `content TEXT`, `error_message TEXT`
- [ ] 更新 `docs/sql/schema.sql` 对齐实际表结构

### Phase 2：领域层（1 天）

- [ ] `models.py`: 新增 `Document` dataclass, `DocStatus` IntEnum
- [ ] `ports.py`: 新增 `DocumentPort`, 扩展 `KnowledgeBasePort`（update, delete）
- [ ] 新增 `adapters/document/pg.py` → `PgDocumentRepository`
- [ ] 重构 `PgKnowledgeBaseRepository`: 移除文档操作，补齐 KB 的 update/delete
- [ ] 调整 `composition.py` DI 注入

### Phase 3：异步索引（2 天）

- [ ] 新增 `celery_app.py`（Celery 实例 + 配置）
- [ ] 新增 `tasks/indexing.py`（`index_document_task`，内部 `asyncio.run()` 桥接）
- [ ] 新增 `application/indexing_service.py`（复用 parser/chunker/embedder/store，不写新索引代码）
- [ ] 重构 `UploadDocumentUseCase`: 拆成 create_record + `task.delay()`
- [ ] Dockerfile 新增 worker 入口或 compose profile

### Phase 4：运维 API（1.5 天）

- [ ] `GET    /v1/documents/{doc_id}` → 状态查询
- [ ] `DELETE /v1/documents/{doc_id}` → purge chunks + 删记录
- [ ] `POST   /v1/documents/{doc_id}/reindex` → purge + 重投递 Celery task
- [ ] `GET    /v1/knowledge-bases/{kb_id}` → KB 详情（含 settings）
- [ ] `PATCH  /v1/knowledge-bases/{kb_id}` → 更新 name/description/settings
- [ ] `DELETE /v1/knowledge-bases/{kb_id}` → 级联删除
- [ ] `tree` 接口：DocNode 加 `status: int` + `error_message: str | None`

### Phase 5：前端（2 天）

- [ ] types/services 扩展
- [ ] 上传页：PROCESSING 即成功，提示"已提交，正在后台索引"
- [ ] 列表页：三种状态 badge（黄色索引中/绿色成功/红色失败）+ 3s 轮询 + 删除/重试按钮
- [ ] EditKBDialog（name + description + settings JSON）+ ConfirmDialog

## 五、文件变更清单

| Phase | 新增 | 修改 | 重构 |
|-------|:---:|:---:|:---:|
| 1 | 1 (migration) | 3 (compose,config,deps) | — |
| 2 | 1 (PgDocumentRepo) | 2 (models,ports) | 2 (PgKBRepo,composition) |
| 3 | 2 (celery_app,tasks/indexing) + 1 (IndexingService) | — | 1 (UploadUseCase) |
| 4 | 4 (doc_router,kb_router,doc_uc,reindex_uc) | 2 (composition,kb_tree) | — |
| 5 | 2 (EditKBDialog,ConfirmDialog) | 5 (types,services,pages) | — |
| **合计** | **11** | **12** | **3** |

估计 **7 人天**。

## 六、关键风险

| 风险 | 缓解 |
|------|------|
| Worker 崩溃 → 文档永久 PROCESSING | Celery beat 定时任务标记超时 → FAILED |
| Celery task 内 `asyncio.run()` 与现有 async 代码的兼容 | IndexingService 本身是 async class，`asyncio.run()` 创建新 event loop，与 API 的 loop 隔离，无冲突 |
| 删库时 Worker 正在索引该库文档 | 删库前检查 PROCESSING 文档，必要时分布式锁 |
| ES+PG 双写一致性问题 | 复用现有事务逻辑（双成功才 commit） |

---

*分析时间: 2026-07-05 | 任务队列: Celery + Redis | 重构优先，不考虑向后兼容*
