---
comet_change: async-indexing-lifecycle
role: technical-design
canonical_spec: openspec
---

# 异步索引与运维 API — 技术设计

## 1. 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        docker-compose                               │
│                                                                     │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐  │
│  │  Redis   │     │PostgreSQL│     │   API    │     │  Worker  │  │
│  │  :6379   │     │  :5432   │     │  :8000   │     │  Celery  │  │
│  │  broker  │     │ pgvector │     │ FastAPI  │     │  async   │  │
│  │  backend │     │  + data  │     │          │     │  tasks   │  │
│  └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘  │
│       │                │                │                │         │
│       │                │     ┌──────────┴────────────────┘         │
│       │                │     │  build_indexing_services(cfg)       │
│       │                │     │  ┌──────────────────────────┐       │
│       │                │     │  │ embedder, parser, chunker │       │
│       │                │     │  │ store, keyword_store     │       │
│       │                │     │  │ kb_repo, llm, reranker   │       │
│       │                │     └────────────────────────────┘       │
│       │                │                                          │
│  ┌────┴────────────────┴──────────────────────────────────────┐   │
│  │                    Elasticsearch :9200                      │   │
│  │                      BM25 keyword index                     │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

**关键变更**：新增 Redis + Worker 服务；API 和 Worker 共享 `build_indexing_services(cfg)` DI 工厂。

## 2. 数据流

### 2.1 上传流程（异步后）

```
HTTP POST /v1/documents:upload
│
├─ 1. 校验（扩展名/大小/KB归属）         ← 不变
├─ 2. SHA256 去重                       ← 不变
├─ 3. INSERT documents                   ← 新增: content 落库, status=PROCESSING
├─ 4. index_document_task.delay(doc_id)  ← 新增: 投递 Celery task
└─ 5. 返回 {doc_id, status: PROCESSING, chunk_count: 0}

         ┌─────────────────────────────────────┐
         │         Celery Worker               │
         │                                     │
         │  index_document_task(doc_id)        │
         │    │                                │
         │    ├─ asyncio.run(                  │
         │    │    IndexingService.execute(    │
         │    │      doc_id                    │
         │    │    )                           │
         │    │  )                             │
         │    │                                │
         │    ├─ 成功 → clear_cache(kb_id)     │
         │    │      → fire-and-forget 词表同步 │
         │    │                                │
         │    └─ 失败 → retry(2次, delay=10s)  │
         │          → 耗尽 → status=FAILED     │
         └─────────────────────────────────────┘
```

### 2.2 IndexingService 内部（复用现有代码）

```python
class IndexingService:
    def __init__(self, parser, chunker, embedder, store,
                 keyword_store, doc_repo, kb_repo):
        ...

    async def execute(self, doc_id: str) -> None:
        doc = await self.doc_repo.get(doc_id)
        if doc.status != DocStatus.PROCESSING:
            return  # 幂等保护

        # ↓ 以下代码与当前 UploadDocumentUseCase 完全相同 ↓
        parsed = await self.parser.parse(doc.content.encode(), doc.filename)
        chunk_dicts = self.chunker(parsed, ...)
        vectors = await self.embedder.embed([c["text"] for c in chunk_dicts])
        chunks = [Chunk(...) for ...]
        await self._dual_write(doc.kb_id, chunks)

        await self.doc_repo.update_status(
            doc_id, DocStatus.SUCCESS, None, len(chunks)
        )
```

### 2.3 文档生命周期状态机

```
                 ┌──────────────┐
     upload ───→ │  PROCESSING  │ ←─── reindex (仅从 FAILED)
                 │    (2)       │
                 └──────┬───────┘
                 ┌──────┴───────┐
                 ▼              ▼
            ┌─────────┐   ┌─────────┐
            │ SUCCESS │   │ FAILED  │
            │   (1)   │   │   (3)   │
            └─────────┘   └─────────┘
              │    ▲           │    ▲
              │    │           │    │
              └────┘           └────┘
            删除允许         删除允许
            reindex拒绝      reindex允许
```

Worker 崩溃恢复：Celery beat 每 5 分钟扫描 `status=PROCESSING AND updated_at < now() - 30min` → 标记 FAILED。

## 3. 组件设计

### 3.1 新增文件清单

```
src/ragnexus/
├── celery_app.py              ← Celery 实例 + beat schedule
├── di.py                      ← build_indexing_services(cfg) 共享工厂
├── domain/
│   └── models.py              ← 新增 Document, DocStatus
│   └── ports.py               ← 新增 DocumentPort
├── application/
│   ├── indexing_service.py    ← 复用索引逻辑
│   ├── document_query_uc.py   ← GET /documents/{id}
│   ├── document_delete_uc.py  ← DELETE /documents/{id}
│   ├── document_reindex_uc.py ← POST /documents/{id}/reindex
│   ├── kb_detail_uc.py        ← GET /knowledge-bases/{id}
│   ├── kb_update_uc.py        ← PATCH /knowledge-bases/{id}
│   └── kb_delete_uc.py        ← DELETE /knowledge-bases/{id}
├── adapters/
│   └── document/
│       └── pg.py              ← PgDocumentRepository
└── tasks/
    └── indexing.py            ← index_document_task + timeout_monitor_task
```

### 3.2 DocumentPort 契约

```python
class DocumentPort(Protocol):
    async def get(self, doc_id: str) -> Document | None: ...
    async def create(self, *, doc_id, kb_id, filename, file_hash,
                     file_size, content_type, content) -> Document: ...
    async def update_status(self, doc_id: str, *,
        status: DocStatus, error_message: str | None,
        chunk_count: int) -> None: ...
    async def delete(self, doc_id: str) -> None: ...
    async def delete_by_kb(self, kb_id: str) -> None: ...
    async def has_processing(self, kb_id: str) -> bool: ...
    async def get_by_kb(self, kb_id: str) -> list[Document]: ...
```

### 3.3 KnowledgeBasePort 扩展

```python
# 新增方法
async def update(self, kb_id: str, *,
    name: str | None, description: str | None,
    settings: dict | None) -> KnowledgeBase: ...

async def delete(self, kb_id: str) -> None: ...

# 已有方法保持不变
```

### 3.4 purge_document_chunks 工具方法

```python
async def purge_document_chunks(
    doc_id: str,
    store: VectorStorePort,       # PG CASCADE 自动清理
    keyword_store: KeywordSearchPort | None,  # ES 显式删除
) -> None:
    if keyword_store is not None:
        await keyword_store.delete_by_document(doc_id)
    # PG 端由 documents 表的 ON DELETE CASCADE 自动处理 chunks
```

### 3.5 Celery 配置

```python
# celery_app.py
from celery import Celery

app = Celery("ragnexus")
app.config_from_object({
    "broker_url": settings.CELERY_BROKER_URL,
    "result_backend": settings.CELERY_RESULT_BACKEND,
    "task_serializer": "json",
    "beat_schedule": {
        "monitor-timeout-docs": {
            "task": "tasks.indexing.monitor_timeout_docs",
            "schedule": 300.0,  # 每5分钟
        },
    },
})
```

## 4. 新增 API 端点

| 方法 | 路径 | UseCase | 说明 |
|------|------|---------|------|
| GET | /v1/documents/{doc_id} | DocumentQueryUseCase | 状态查询，校验租户归属 |
| DELETE | /v1/documents/{doc_id} | DocumentDeleteUseCase | PROCESSING 时拒绝 |
| POST | /v1/documents/{doc_id}/reindex | DocumentReindexUseCase | 仅 FAILED 允许 |
| GET | /v1/knowledge-bases/{kb_id} | KnowledgeBaseDetailUseCase | 含完整 settings |
| PATCH | /v1/knowledge-bases/{kb_id} | KnowledgeBaseUpdateUseCase | 字段可选，settings 整段替换 |
| DELETE | /v1/knowledge-bases/{kb_id} | KnowledgeBaseDeleteUseCase | 库下有 PROCESSING 文档时拒绝 |

所有路由统一走 `Depends(get_current_tenant)`。

## 5. 数据库变更

```sql
-- Alembic migration: documents 表新增列
ALTER TABLE documents ADD COLUMN status INTEGER NOT NULL DEFAULT 1;
ALTER TABLE documents ADD COLUMN content TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN error_message TEXT;
ALTER TABLE documents ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- 同步 schema.sql: knowledge_bases 表已有但未记录的列
-- tenant_id TEXT, description TEXT, settings JSONB (实际已通过更早的 migration 存在)
```

## 6. 前端适配

| 页面/组件 | 改动 |
|-----------|------|
| 上传页 | upload 响应适配 PROCESSING，Toast "已提交，正在后台索引" |
| 列表页 | StatusBadge（黄=索引中, 绿=成功, 红=失败）；PROCESSING 时 3s 轮询 tree |
| 文档行 | 删除按钮（SUCCESS/FAILED）+ 重试按钮（仅 FAILED） |
| KB 行 | 编辑入口 → EditKBDialog + 删除入口 → ConfirmDialog |
| EditKBDialog | name Input + description Textarea + settings Textarea（等宽字体） |
| ConfirmDialog | 复用组件，删文档/删 KB 共用 |

## 7. 测试计划

### 单元测试
- `TestIndexingService`: execute 正常流程、幂等保护（status≠PROCESSING 时 return）
- `TestPgDocumentRepository`: create/get/update_status/delete/has_processing
- `TestPgKnowledgeBaseRepository`: update/delete

### 集成测试
- `TestAsyncUploadFullChain`: 上传→轮询→SUCCESS→检索命中
- `TestIndexFailureAndReindex`: ES 停→FAILED→ES 启→reindex→SUCCESS
- `TestKbCrud`: GET/PATCH/DELETE 全覆盖，PATCH 非法 settings 报错
- `TestCrossTenantIsolation`: 所有新路由的跨租户访问 → NOT_FOUND

### E2E 测试
- `TestProcessingRejections`: PROCESSING 时 DELETE 文档/delete KB 被拒绝
- `TestDeleteWithProcessing`: 库下有 PROCESSING 文档时 DELETE KB 被拒绝
