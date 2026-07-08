---
change: async-indexing-lifecycle
design-doc: docs/superpowers/specs/2026-07-05-async-indexing-lifecycle-design.md
base-ref: 2ef29c697acf5ec10c0eda7218010e8ec9de1ba9
---
# 异步索引与运维 API 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox () syntax for tracking.

**Goal:** 将文档上传从同步流水线改造为异步索引架构——引入 Redis + Celery Worker，新增文档状态机（PROCESSING/SUCCESS/FAILED）、6 个运维 API 端点、前端状态适配。

**Architecture:** API 层接收上传后立即返回 PROCESSING 状态，Celery Worker 异步执行解析→分块→嵌入→双写。新增 DocumentPort 将文档操作从 KnowledgeBasePort 中独立出来。shared DI 工厂 \ 供 API 和 Worker 复用。


**Tech Stack:** FastAPI, asyncpg, Celery 5.4+, Redis, Elasticsearch 8.17, pgvector, Alembic

## Global Constraints

- Python >= 3.11, FastAPI >= 0.110, celery[redis] >= 5.4.0, redis >= 5.0.0
- 所有新路由 MUST 通过 \ 校验租户归属

- 跨租户访问 MUST 返回 NOT_FOUND（不泄露存在性）
- PROCESSING 状态的文档拒绝删除；库下有 PROCESSING 文档时拒绝删除 KB
- reindex 仅对 FAILED 状态允许
- 前端需适配三种文档状态：PROCESSING（黄）、SUCCESS（绿）、FAILED（红）
- 单元测试 MUST 使用 \（MagicMock/AsyncMock），集成测试通过 \ 模拟 HTTP 调用

- 迁移 MUST 使用原始 SQL（alembic + raw SQL），不使用 ORM


## File Structure

### 新增文件
```
src/ragnexus/
├── celery_app.py              # Celery 实例 + beat schedule
├── di.py                      # build_indexing_services(cfg) 共享工厂
├── domain/
│   └── models.py              # + Document dataclass, DocStatus IntEnum
│   └── ports.py               # + DocumentPort Protocol
├── application/
│   ├── indexing_service.py    # 复用索引逻辑
│   ├── document_query_uc.py   # GET /documents/{id}
│   ├── document_delete_uc.py  # DELETE /documents/{id}
│   ├── document_reindex_uc.py # POST /documents/{id}/reindex
│   ├── kb_detail_uc.py        # GET /knowledge-bases/{id}
│   ├── kb_update_uc.py        # PATCH /knowledge-bases/{id}
│   └── kb_delete_uc.py        # DELETE /knowledge-bases/{id}
├── adapters/
│   └── document/
│       └── pg.py              # PgDocumentRepository
└── tasks/
    ├── __init__.py
    └── indexing.py            # index_document_task + timeout monitor
```

### 修改文件
```
src/ragnexus/
├── config.py                  # + CELERY_BROKER_URL, CELERY_RESULT_BACKEND, INDEX_TIMEOUT_MINUTES
├── domain/models.py           # + Document, DocStatus; UploadResult +status; DocNode +error_message
├── domain/ports.py            # + DocumentPort; KnowledgeBasePort +update/delete/has_processing
├── composition.py             # + 新 use case 装配, 重构 UploadDocumentUseCase 拆分
├── adapters/knowledge_base/pg.py  # + update/delete KB; 移除嵌入式文档操作
├── adapters/http/upload_doc_router.py  # 适配新 UploadResult
├── application/upload_doc_use_case.py  # 拆分为 create_document_record + task.delay()
tests/
├── unit/application/test_upload_doc.py  # 适配重构后的 use case
├── unit/adapters/test_kb_repo.py        # + update/delete 测试
├── integration/test_upload_full_chain.py # 适配异步索引链路
docker-compose.yml            # + Redis + Worker 服务
pyproject.toml                # + celery[redis], redis 依赖
docs/sql/schema.sql           # 同步 knowledge_bases 实际列
```

---

## Phase 1: 基础设施 (Tasks 1.1–1.5)

### Task 1.1: docker-compose.yml 增加 Redis + Celery worker 服务

**Files:**
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: 无
- Produces: Redis 服务 (端口 6379), Worker 服务 (基于 app Dockerfile)

- [ ] **Step 1: 添加 Redis 服务定义**

在 `docker-compose.yml` 的 `services:` 下，`elasticsearch` 之前插入：

```yaml
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 2s
      timeout: 3s
      retries: 30
    volumes:
      - redisdata:/data
```

- [ ] **Step 2: 添加 Worker 服务定义**

在 `services:` 末尾（`volumes:` 之前）添加：

```yaml
  worker:
    build: .
    command: celery -A src.ragnexus.celery_app worker --loglevel=info --concurrency=2
    env_file: .env
    environment:
      PG_DSN: postgresql://ragnexus:ragnexus@db:5432/ragnexus
      ELASTICSEARCH_URL: http://elasticsearch:9200
      ES_ENABLED: "true"
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/0
    depends_on:
      init-db:
        condition: service_completed_successfully
      elasticsearch:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  beat:
    build: .
    command: celery -A src.ragnexus.celery_app beat --loglevel=info
    env_file: .env
    environment:
      PG_DSN: postgresql://ragnexus:ragnexus@db:5432/ragnexus
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/0
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped
```

- [ ] **Step 3: 添加 redisdata volume**

在 `volumes:` 末尾添加：

```yaml
  redisdata:
```

- [ ] **Step 4: 更新 app 服务的 depends_on 添加 redis**

在 `app` 服务的 `depends_on` 末尾添加：

```yaml
      redis:
        condition: service_healthy
```

- [ ] **Step 5: 验证**

```bash
docker compose config --services
# 预期输出包含: redis, worker, beat
```

---

### Task 1.2: pyproject.toml 增加依赖

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 在 dependencies 列表末尾添加**

```toml
  "celery[redis]>=5.4.0,<6.0",
  "redis>=5.0.0,<6.0",
```

位置：`"elasticsearch[async]>=8.0,<9.0"` 之后。

- [ ] **Step 2: 安装新依赖**

```bash
uv sync
```

- [ ] **Step 3: 验证导入**

```bash
python -c "import celery; print(celery.__version__)"
python -c "import redis; print(redis.__version__)"
```

---

### Task 1.3: Settings 增加 Celery 配置

**Files:**
- Modify: `src/ragnexus/config.py`（Settings 类）

- [ ] **Step 1: 在 `Settings` 类末尾添加三个字段**

在 `RRF_K` 之后添加：

```python
    # Celery / Async indexing
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    INDEX_TIMEOUT_MINUTES: int = 30
```

- [ ] **Step 2: 更新 docstring 中的字段计数**

将 `"""51 个配置字段..."""` 改为 `"""54 个配置字段..."""`。

- [ ] **Step 3: 验证**

```bash
python -c "from ragnexus.config import get_settings; s=get_settings(); print(s.CELERY_BROKER_URL, s.INDEX_TIMEOUT_MINUTES)"
# 预期: redis://localhost:6379/0 30
```

---

### Task 1.4: Alembic migration — documents 表加列

**Files:**
- Create: `alembic/versions/0006_document_status.py`

**Interfaces:**
- Consumes: documents 表当前结构 (schema.sql / migration 0001)
- Produces: documents 表含 status INT DEFAULT 2, content TEXT, error_message TEXT, updated_at TIMESTAMPTZ

- [ ] **Step 1: 创建迁移文件**

```bash
alembic revision -m "document_status"
```

- [ ] **Step 2: 编辑 migration**

```python
"""document_status — 添加 status/content/error_message/updated_at 列

Revision ID: <auto-generated>
Revises: 0005_kb_description
Create Date: <auto-generated>
"""

from typing import Sequence, Union
from alembic import op

revision: str = "<auto-generated>"
down_revision: Union[str, None] = "0005_kb_description"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS status INTEGER NOT NULL DEFAULT 2")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS content TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS error_message TEXT")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")


def downgrade() -> None:
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS content")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS error_message")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS updated_at")
```

- [ ] **Step 3: 更新 revision ID**

```bash
# revision ID 已由 alembic 自动生成，确认 up/down revision 链正确
grep "revision\|down_revision" alembic/versions/0006_document_status.py
```

- [ ] **Step 4: 运行迁移并验证**

```bash
alembic upgrade head
# 验证列存在
python -c "
import asyncio, asyncpg
async def check():
    conn = await asyncpg.connect('postgresql://ragnexus:ragnexus@localhost:15432/ragnexus')
    cols = await conn.fetch(\"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='documents'\")
    for c in cols: print(c['column_name'], c['data_type'])
    await conn.close()
asyncio.run(check())
"
```

---

### Task 1.5: 更新 schema.sql 对齐实际表结构

**Files:**
- Modify: `docs/sql/schema.sql`

- [ ] **Step 1: 在 knowledge_bases 表定义中补齐已存在但未记录的列**

在 `knowledge_bases` 表 DDL 中添加：

```sql
    tenant_id TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
```

- [ ] **Step 2: 在 documents 表 DDL 中添加新列**

```sql
    status INTEGER NOT NULL DEFAULT 2,
    content TEXT NOT NULL DEFAULT '',
    error_message TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
```

- [ ] **Step 3: 验证 schema.sql 可通过 psql 执行（dry-run）**

```bash
# 语法检查
python -c "
with open('docs/sql/schema.sql') as f:
    content = f.read()
# 基本检查: 以分号结尾的语句配对
statements = [s.strip() for s in content.split(';') if s.strip() and not s.strip().startswith('--')]
print(f'Found {len(statements)} SQL statements')
for i, s in enumerate(statements):
    print(f'  Stmt {i+1}: {s[:60]}...')
"
```

---

## Phase 2: 领域层 (Tasks 2.1–2.8)

### Task 2.1: models.py — 新增 Document dataclass + DocStatus IntEnum

**Files:**
- Modify: `src/ragnexus/domain/models.py`

**Interfaces:**
- Consumes: 无
- Produces: `DocStatus(IntEnum)` — PROCESSING=2, SUCCESS=1, FAILED=3; `Document` dataclass

- [ ] **Step 1: 在文件顶部 `from enum import IntEnum` 添加导入**

修改现有 `from dataclasses import dataclass, field` 下方：

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any
```

- [ ] **Step 2: 在 `KnowledgeBase` 类前面添加 DocStatus**

```python
class DocStatus(IntEnum):
    """文档索引状态枚举 — 与数据库 INTEGER 字段映射。"""
    SUCCESS = 1       # 索引成功
    PROCESSING = 2    # 索引中（默认值）
    FAILED = 3        # 索引失败
```

- [ ] **Step 3: 在 `UploadResult` 类后面添加 Document**

```python
@dataclass
class Document:
    """文档领域模型 — 对应 documents 表完整行。"""
    doc_id: str
    kb_id: str
    filename: str
    file_hash: str
    file_size: int
    content_type: str
    content: str
    status: DocStatus = DocStatus.PROCESSING
    chunk_count: int = 0
    error_message: str | None = None
    uploaded_at: datetime | None = None
    updated_at: datetime | None = None
```

- [ ] **Step 4: 验证导入**

```bash
python -c "from ragnexus.domain.models import DocStatus, Document; print(DocStatus.PROCESSING, DocStatus.PROCESSING.value)"
# 预期: DocStatus.PROCESSING 2
```

---

### Task 2.2: models.py — UploadResult 增加 status 字段

**Files:**
- Modify: `src/ragnexus/domain/models.py`

- [ ] **Step 1: 修改 UploadResult dataclass**

将现有：

```python
@dataclass
class UploadResult:
    doc_id: str
    kb_id: str
    chunks: list[Chunk]
    chunk_count: int = 0
```

改为：

```python
@dataclass
class UploadResult:
    doc_id: str
    kb_id: str
    status: DocStatus
    chunks: list[Chunk] = field(default_factory=list)
    chunk_count: int = 0
```

- [ ] **Step 2: 更新 upload_doc_router.py 中 UploadResult 的构造**

查找 `composition.py` 中 `UploadResult(doc_id=doc_id, kb_id=kb_id, chunks=chunks, chunk_count=len(chunks))` 调用处，添加 `status=DocStatus.SUCCESS`。此步骤在 Task 3.4 中统一完成。

---

### Task 2.3: models.py — DocNode / KBNode 增加字段

**Files:**
- Modify: `src/ragnexus/domain/models.py`

- [ ] **Step 1: DocNode 添加 error_message**

```python
@dataclass
class DocNode:
    """文档节点 — Tree API 中文档的轻量表示。"""
    doc_id: str
    filename: str
    status: str
    uploaded_at: str
    error_message: str | None = None
```

注意：`status: str` 保持现有类型（tree API 序列化为字符串，值为 `"processing" | "success" | "failed"`）。

- [ ] **Step 2: KBNode 无新增字段**（description 已在 0005 migration 中添加，从 DB 读取）

无需修改 KBNode，确认 `list_with_documents` 返回时已包含 description。

---

### Task 2.4: ports.py — 新增 DocumentPort Protocol

**Files:**
- Modify: `src/ragnexus/domain/ports.py`

- [ ] **Step 1: 在导入中添加 Document, DocStatus**

```python
from ragnexus.domain.models import (
    Chunk,
    DocStatus,
    Document,
    KnowledgeBase,
    ParsedDocument,
    SearchHit,
    TenantKBTree,
)
```

- [ ] **Step 2: 在 KeywordSearchPort 之后（RewritePort 之前）添加 DocumentPort**

```python
class DocumentPort(Protocol):
    """文档 CRUD 端口 — 从 KnowledgeBasePort 独立出的文档操作。"""

    async def get(self, doc_id: str) -> Document | None: ...

    async def create(
        self,
        *,
        doc_id: str,
        kb_id: str,
        filename: str,
        file_hash: str,
        file_size: int,
        content_type: str,
        content: str,
    ) -> Document: ...

    async def update_status(
        self,
        doc_id: str,
        *,
        status: DocStatus,
        error_message: str | None = None,
        chunk_count: int | None = None,
    ) -> None: ...

    async def delete(self, doc_id: str) -> None: ...

    async def delete_by_kb(self, kb_id: str) -> None: ...

    async def has_processing(self, kb_id: str) -> bool: ...

    async def get_by_kb(self, kb_id: str) -> list[Document]: ...
```

- [ ] **Step 3: 验证**

```bash
python -c "from ragnexus.domain.ports import DocumentPort; print('DocumentPort imported OK')"
```

---

### Task 2.5: ports.py — KnowledgeBasePort 扩展

**Files:**
- Modify: `src/ragnexus/domain/ports.py`

- [ ] **Step 1: 在 KnowledgeBasePort 的 update_settings 方法下方添加三个新方法**

```python
    async def update(
        self,
        kb_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        settings: dict | None = None,
    ) -> KnowledgeBase: ...

    async def delete(self, kb_id: str) -> None: ...

    async def has_processing_docs(self, kb_id: str) -> bool:
        """检查知识库下是否有 PROCESSING 状态的文档。"""
        ...
```

注意：`has_processing_docs` 与 `DocumentPort.has_processing` 职责不同——前者供 KB 删除前检查，调用后者的实现。

---

### Task 2.6: 新增 PgDocumentRepository

**Files:**
- Create: `src/ragnexus/adapters/document/__init__.py`
- Create: `src/ragnexus/adapters/document/pg.py`

**Interfaces:**
- Consumes: `asyncpg.Pool`, `DocumentPort` 契约
- Produces: `PgDocumentRepository` 实现类

- [ ] **Step 1: 创建 `__init__.py`**

```python
"""Document adapters."""
```

- [ ] **Step 2: 创建 `pg.py`**

```python
"""PgDocumentRepository — 文档 CRUD 适配器。"""

from datetime import datetime, UTC

import asyncpg

from ragnexus.domain.models import DocStatus, Document
from ragnexus.domain.ports import DocumentPort


class PgDocumentRepository:
    """Postgres (asyncpg) 文档 CRUD 适配器。"""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def get(self, doc_id: str) -> Document | None:
        row = await self.pool.fetchrow(
            "SELECT doc_id, kb_id, filename, file_hash, file_size, "
            "content_type, content, status, chunk_count, "
            "error_message, uploaded_at, updated_at "
            "FROM documents WHERE doc_id = $1",
            doc_id,
        )
        if row is None:
            return None
        return Document(
            doc_id=row["doc_id"],
            kb_id=row["kb_id"],
            filename=row["filename"],
            file_hash=row["file_hash"],
            file_size=row["file_size"],
            content_type=row["content_type"],
            content=row["content"] or "",
            status=DocStatus(row["status"]),
            chunk_count=row["chunk_count"] or 0,
            error_message=row["error_message"],
            uploaded_at=row["uploaded_at"],
            updated_at=row["updated_at"],
        )

    async def create(self, *, doc_id, kb_id, filename, file_hash,
                     file_size, content_type, content) -> Document:
        now = datetime.now(UTC)
        await self.pool.execute(
            "INSERT INTO documents (doc_id, kb_id, filename, file_hash, "
            "file_size, content_type, content, status, uploaded_at, updated_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
            doc_id, kb_id, filename, file_hash,
            file_size, content_type, content,
            DocStatus.PROCESSING.value, now, now,
        )
        return Document(
            doc_id=doc_id, kb_id=kb_id, filename=filename,
            file_hash=file_hash, file_size=file_size,
            content_type=content_type, content=content,
            status=DocStatus.PROCESSING, uploaded_at=now, updated_at=now,
        )

    async def update_status(self, doc_id, *, status, error_message=None,
                            chunk_count=None) -> None:
        updates = ["status = $1", "updated_at = $2"]
        params: list = [status.value, datetime.now(UTC)]
        idx = 3
        if error_message is not None:
            updates.append(f"error_message = ${idx}")
            params.append(error_message)
            idx += 1
        if chunk_count is not None:
            updates.append(f"chunk_count = ${idx}")
            params.append(chunk_count)
            idx += 1
        params.append(doc_id)
        await self.pool.execute(
            f"UPDATE documents SET {', '.join(updates)} WHERE doc_id = ${idx}",
            *params,
        )

    async def delete(self, doc_id: str) -> None:
        await self.pool.execute("DELETE FROM documents WHERE doc_id = $1", doc_id)

    async def delete_by_kb(self, kb_id: str) -> None:
        await self.pool.execute("DELETE FROM documents WHERE kb_id = $1", kb_id)

    async def has_processing(self, kb_id: str) -> bool:
        result = await self.pool.fetchval(
            "SELECT 1 FROM documents WHERE kb_id = $1 AND status = $2 LIMIT 1",
            kb_id, DocStatus.PROCESSING.value,
        )
        return result is not None

    async def get_by_kb(self, kb_id: str) -> list[Document]:
        rows = await self.pool.fetch(
            "SELECT doc_id, kb_id, filename, file_hash, file_size, "
            "content_type, content, status, chunk_count, "
            "error_message, uploaded_at, updated_at "
            "FROM documents WHERE kb_id = $1 ORDER BY uploaded_at DESC",
            kb_id,
        )
        return [
            Document(
                doc_id=r["doc_id"], kb_id=r["kb_id"], filename=r["filename"],
                file_hash=r["file_hash"], file_size=r["file_size"],
                content_type=r["content_type"], content=r["content"] or "",
                status=DocStatus(r["status"]),
                chunk_count=r["chunk_count"] or 0,
                error_message=r["error_message"],
                uploaded_at=r["uploaded_at"], updated_at=r["updated_at"],
            )
            for r in rows
        ]
```

---

### Task 2.7: PgKnowledgeBaseRepository — 扩展 update/delete，移除嵌入文档操作

**Files:**
- Modify: `src/ragnexus/adapters/knowledge_base/pg.py`

- [ ] **Step 1: 添加 `update` 方法**

在 `update_settings` 方法之后添加：

```python
    async def update(
        self,
        kb_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        settings: dict | None = None,
    ) -> KnowledgeBase:
        """更新知识库字段。仅更新传入的非 None 字段。"""
        import json as _json
        sets: list[str] = []
        params: list = []
        idx = 1

        if name is not None:
            sets.append(f"name = ${idx}")
            params.append(name)
            idx += 1
        if description is not None:
            sets.append(f"description = ${idx}")
            params.append(description)
            idx += 1
        if settings is not None:
            sets.append(f"settings = ${idx}::jsonb")
            params.append(_json.dumps(settings, ensure_ascii=False))
            idx += 1

        if not sets:
            # 无变更，返回当前 KB
            return await self.get(kb_id)  # type: ignore[return-value]

        params.append(kb_id)
        row = await self.pool.fetchrow(
            f"UPDATE knowledge_bases SET {', '.join(sets)} WHERE id = ${idx} "
            "RETURNING id, name, description, tenant_id, created_at, settings",
            *params,
        )
        if row is None:
            from ragnexus.core.errors import AppError, ErrorCode
            raise AppError(ErrorCode.NOT_FOUND, f"知识库 {kb_id} 不存在")
        return KnowledgeBase(
            id=row["id"], name=row["name"],
            description=row["description"] or "",
            tenant_id=row["tenant_id"],
            created_at=row["created_at"],
            settings=row["settings"] or {},
        )
```

- [ ] **Step 2: 添加 `delete` 方法**

```python
    async def delete(self, kb_id: str) -> None:
        """删除知识库。"""
        await self.pool.execute("DELETE FROM knowledge_bases WHERE id = $1", kb_id)
```

- [ ] **Step 3: 添加 `has_processing_docs` 方法**

```python
    async def has_processing_docs(self, kb_id: str) -> bool:
        """检查知识库下是否有 PROCESSING 状态的文档。"""
        result = await self.pool.fetchval(
            "SELECT 1 FROM documents WHERE kb_id = $1 AND status = 2 LIMIT 1",
            kb_id,
        )
        return result is not None
```

注意：此处直接硬编码 `status = 2`（DocStatus.PROCESSING.value），避免循环导入 DocStatus。

---

### Task 2.8: composition.py — 注入新的 document_repo

**Files:**
- Modify: `src/ragnexus/composition.py`

- [ ] **Step 1: 添加导入**

在现有适配器导入附近添加：

```python
from ragnexus.adapters.document.pg import PgDocumentRepository
```

- [ ] **Step 2: 在 kb_repo 实例化之后添加 document_repo**

在 `kb_repo = PgKnowledgeBaseRepository(pool=cast(Any, repo_pool))` 之后：

```python
        document_repo = PgDocumentRepository(pool=cast(Any, repo_pool))
```

- [ ] **Step 3: 将 document_repo 传递给 use case 构造**

在 Task 3.4 (重构 UploadDocumentUseCase) 和 Task 4.x (新 use case) 中完成。

此步骤只做注入占位：不改变现有行为。

---

## Phase 3: 异步索引核心 (Tasks 3.1–3.6)

### Task 3.1: celery_app.py — Celery 实例 + beat schedule

**Files:**
- Create: `src/ragnexus/celery_app.py`

- [ ] **Step 1: 创建 celery_app.py**

```python
"""Celery 应用实例 — 供 Worker 和 Beat 进程使用。"""

from celery import Celery
from celery.schedules import crontab

from ragnexus.config import get_settings

settings = get_settings()

app = Celery("ragnexus")
app.config_from_object({
    "broker_url": settings.CELERY_BROKER_URL,
    "result_backend": settings.CELERY_RESULT_BACKEND,
    "task_serializer": "json",
    "result_serializer": "json",
    "accept_content": ["json"],
    "timezone": "Asia/Shanghai",
    "enable_utc": True,
    "task_track_started": True,
    "task_acks_late": True,
    "worker_prefetch_multiplier": 1,
    "beat_schedule": {
        "monitor-timeout-docs": {
            "task": "ragnexus.tasks.indexing.monitor_timeout_docs",
            "schedule": 300.0,  # 每 5 分钟
        },
    },
})

# 自动发现 tasks 模块
app.autodiscover_tasks(["ragnexus.tasks"])
```

- [ ] **Step 2: 验证 Celery 实例可加载**

```bash
python -c "from ragnexus.celery_app import app; print(app.main, app.conf.broker_url)"
# 预期: ragnexus redis://localhost:6379/0
```

---

### Task 3.2: indexing_service.py — 复用索引逻辑

**Files:**
- Create: `src/ragnexus/application/indexing_service.py`

**Interfaces:**
- Consumes: DocumentPort, ParserPort, chunker Callable, EmbedderPort, VectorStorePort, KeywordSearchPort | None
- Produces: `IndexingService.execute(doc_id: str) -> None`

- [ ] **Step 1: 创建 indexing_service.py**

```python
"""IndexingService — 复用 UploadDocumentUseCase 的解析→分块→嵌入→双写逻辑。"""

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.core.logger import logger
from ragnexus.domain.models import Chunk, DocStatus
from ragnexus.domain.ports import (
    DocumentPort,
    EmbedderPort,
    KeywordSearchPort,
    ParserPort,
    VectorStorePort,
)

if TYPE_CHECKING:
    from ragnexus.adapters.vector_store.pgvector import PgVectorStore


class IndexingService:
    """异步执行文档索引 — 解析→分块→嵌入→双写。"""

    def __init__(
        self,
        doc_repo: DocumentPort,
        parser: ParserPort,
        embedder: EmbedderPort,
        chunker: Callable[..., list[dict]],
        store: VectorStorePort,
        keyword_store: KeywordSearchPort | None = None,
        es_enabled: bool = False,
        chunk_max_chars: int = 1500,
        chunk_overlap: int = 50,
    ) -> None:
        self._doc_repo = doc_repo
        self._parser = parser
        self._embedder = embedder
        self._chunker = chunker
        self._store = store
        self._pg_store: PgVectorStore = store  # type: ignore[assignment]
        self._keyword_store = keyword_store
        self._es_enabled = es_enabled
        self._chunk_max_chars = chunk_max_chars
        self._chunk_overlap = chunk_overlap

    async def execute(self, doc_id: str) -> None:
        """执行索引流水线。

        幂等保护：如果 doc.status != PROCESSING，直接返回。
        成功：UPDATE status=SUCCESS, chunk_count
        失败：UPDATE status=FAILED, error_message（由 Celery retry 机制驱动）
        """
        doc = await self._doc_repo.get(doc_id)
        if doc is None:
            logger.warning("索引任务: 文档不存在", extra={"doc_id": doc_id})
            return
        if doc.status != DocStatus.PROCESSING:
            logger.info("索引任务: 跳过非 PROCESSING 文档",
                        extra={"doc_id": doc_id, "status": doc.status.name})
            return

        try:
            # 1. Parse
            parsed = await self._parser.parse(doc.content.encode(), doc.filename)
            if not parsed.sections and not parsed.raw_text:
                await self._doc_repo.update_status(
                    doc_id, status=DocStatus.FAILED,
                    error_message="文件内容为空",
                )
                return

            # 2. Chunk
            chunk_dicts = self._chunker(
                parsed, max_chars=self._chunk_max_chars, overlap=self._chunk_overlap
            )
            if not chunk_dicts:
                await self._doc_repo.update_status(
                    doc_id, status=DocStatus.FAILED,
                    error_message="分块结果为空",
                )
                return

            # 3. Embed
            texts = [cd["text"] for cd in chunk_dicts]
            vectors = await self._embedder.embed(texts)

            # 4. Build chunks
            common_meta = {
                "filename": doc.filename,
                "file_hash": doc.file_hash,
                "file_size": doc.file_size,
                "content_type": doc.content_type,
            }
            chunks = [
                Chunk(
                    id=f"{doc.doc_id}:{i}",
                    kb_id=doc.kb_id,
                    doc_id=doc.doc_id,
                    text=cd["text"],
                    vector=vectors[i],
                    metadata={
                        **common_meta,
                        "chunk_index": i,
                        "heading": cd.get("heading"),
                        "heading_level": cd.get("heading_level", 0),
                    },
                )
                for i, cd in enumerate(chunk_dicts)
            ]

            # 5. Dual write (复用 UploadDocumentUseCase 的双写模式)
            if self._es_enabled and self._keyword_store is not None:
                conn = await self._pg_store.acquire_connection()
                try:
                    es_task = asyncio.ensure_future(
                        self._keyword_store.upsert(doc.kb_id, chunks)
                    )
                    pg_task = asyncio.ensure_future(
                        self._pg_store._upsert_in_transaction(conn, doc.kb_id, chunks)
                    )
                    done, _ = await asyncio.wait(
                        [es_task, pg_task], return_when=asyncio.ALL_COMPLETED
                    )
                    es_ok = not es_task.exception()
                    pg_ok = not pg_task.exception()

                    if es_ok and pg_ok:
                        await conn.execute("COMMIT")
                    elif not es_ok and not pg_ok:
                        await conn.execute("ROLLBACK")
                        raise pg_task.exception()  # type: ignore[misc]
                    elif pg_ok and not es_ok:
                        await conn.execute("ROLLBACK")
                        raise es_task.exception()  # type: ignore[misc]
                    else:
                        # PG fail, ES ok → cleanup ES orphans
                        try:
                            ids = [c.id for c in chunks]
                            await self._keyword_store.delete(doc.kb_id, ids)
                        except Exception:
                            pass
                        await conn.execute("ROLLBACK")
                        raise pg_task.exception()  # type: ignore[misc]
                finally:
                    await self._pg_store.pool.release(conn)
            else:
                await self._store.upsert(doc.kb_id, chunks)

            # 6. Update to SUCCESS
            await self._doc_repo.update_status(
                doc_id, status=DocStatus.SUCCESS, chunk_count=len(chunks)
            )

            logger.info("文档索引完成", extra={
                "event_type": "BIZ_EVENT",
                "event": "document_indexed",
                "doc_id": doc_id,
                "kb_id": doc.kb_id,
                "chunks": len(chunks),
            })

        except Exception as exc:
            logger.error("文档索引失败", extra={
                "event_type": "BIZ_EVENT",
                "event": "document_index_failed",
                "doc_id": doc_id,
                "error": str(exc),
            })
            await self._doc_repo.update_status(
                doc_id, status=DocStatus.FAILED,
                error_message=str(exc)[:500],
            )
            raise  # 重新抛出以触发 Celery retry
```

---

### Task 3.3: tasks/indexing.py — Celery tasks

**Files:**
- Create: `src/ragnexus/tasks/__init__.py`
- Create: `src/ragnexus/tasks/indexing.py`

- [ ] **Step 1: 创建 `tasks/__init__.py`**

```python
"""Celery 异步任务模块。"""
```

- [ ] **Step 2: 创建 `tasks/indexing.py`**

```python
"""索引相关 Celery 任务 — index_document + timeout monitor。"""

import asyncio
from datetime import datetime, timedelta, UTC

import asyncpg

from ragnexus.celery_app import app
from ragnexus.config import get_settings
from ragnexus.core.logger import logger
from ragnexus.domain.models import DocStatus


@app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    autoretry_for=(Exception,),
)
def index_document_task(self, doc_id: str) -> None:
    """Celery 任务入口 — asyncio.run 桥接到 IndexingService.execute。

    失败自动重试最多 2 次，每次延迟 10 秒。
    3 次全部失败 → status 已在 IndexingService.execute 中设为 FAILED。
    """
    # 延迟导入避免循环依赖（Celery 在 worker 启动时加载 task 模块）
    from ragnexus.di import build_indexing_services

    indexing_svc, doc_repo, kb_repo = build_indexing_services()

    try:
        asyncio.run(indexing_svc.execute(doc_id))
    except Exception as exc:
        logger.warning("索引任务重试", extra={
            "doc_id": doc_id, "retry": self.request.retries, "error": str(exc),
        })
        raise self.retry(exc=exc)


@app.task(name="ragnexus.tasks.indexing.monitor_timeout_docs")
def monitor_timeout_docs() -> None:
    """Celery Beat 周期任务 — 将超时的 PROCESSING 文档标记为 FAILED。

    每 5 分钟执行，扫描 status=PROCESSING 且 updated_at < now() - INDEX_TIMEOUT_MINUTES。
    """
    settings = get_settings()
    timeout = timedelta(minutes=settings.INDEX_TIMEOUT_MINUTES)
    cutoff = datetime.now(UTC) - timeout

    async def _run():
        pool = await asyncpg.create_pool(settings.PG_DSN, min_size=1, max_size=2)
        try:
            result = await pool.execute(
                "UPDATE documents SET status = $1, error_message = $2, updated_at = $3 "
                "WHERE status = $4 AND updated_at < $5",
                DocStatus.FAILED.value,
                "索引超时（Worker 可能崩溃）",
                datetime.now(UTC),
                DocStatus.PROCESSING.value,
                cutoff,
            )
            count = int(result.split()[-1]) if result else 0
            if count > 0:
                logger.warning("超时文档标记为 FAILED", extra={
                    "event_type": "BIZ_EVENT",
                    "event": "timeout_docs_failed",
                    "count": count,
                    "cutoff": cutoff.isoformat(),
                })
        finally:
            await pool.close()

    asyncio.run(_run())
```

---

### Task 3.4: 重构 UploadDocumentUseCase — 拆分 + task.delay()

**Files:**
- Modify: `src/ragnexus/application/upload_doc_use_case.py`
- Create: `src/ragnexus/di.py`

- [ ] **Step 1: 创建 `di.py` — 共享 DI 工厂**

```python
"""Shared DI factory — build_indexing_services(cfg) 供 API 和 Worker 复用。"""

from typing import Any, cast

import asyncpg

from ragnexus.adapters.document.pg import PgDocumentRepository
from ragnexus.adapters.embedder.openai_compat import OpenAICompatEmbedder
from ragnexus.adapters.keyword_search.elasticsearch import ESKeywordSearchProvider
from ragnexus.adapters.knowledge_base.pg import PgKnowledgeBaseRepository
from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser
from ragnexus.adapters.vector_store.pgvector import PgVectorStore
from ragnexus.application.indexing_service import IndexingService
from ragnexus.config import Settings, get_settings
from ragnexus.core.logger import LoggedPool
from ragnexus.domain.chunking import heading_aware_split


def build_indexing_services(cfg: Settings | None = None):
    """构建 IndexingService 及其依赖 — 供 Worker task 使用。

    创建独立连接池（与 API 进程的池分离）。
    返回 (indexing_svc, doc_repo, kb_repo)。

    注意：此函数在 Celery worker 进程中调用，需自行管理连接池生命周期。
    当前设计为每次 task 调用创建/销毁连接池（简单可靠）。
    """
    if cfg is None:
        cfg = get_settings()
    return _build_services(cfg)


def _build_services(cfg: Settings):
    """内部实现 — 创建适配器并组装 IndexingService。"""
    import asyncio

    async def _async_build():
        # Vector store pool
        store_pool = await asyncpg.create_pool(
            cfg.PG_DSN, min_size=1, max_size=3,
            command_timeout=cfg.PG_COMMAND_TIMEOUT,
        )
        store = PgVectorStore(
            dsn=cfg.PG_DSN, pool_min=1, pool_max=3,
            command_timeout=cfg.PG_COMMAND_TIMEOUT,
        )
        await store.connect(external_pool=LoggedPool(store_pool))

        # Repo pool
        repo_pool = await asyncpg.create_pool(
            cfg.PG_DSN, min_size=1, max_size=3,
            command_timeout=cfg.PG_COMMAND_TIMEOUT,
        )
        logged_repo_pool = LoggedPool(repo_pool)

        kb_repo = PgKnowledgeBaseRepository(pool=cast(Any, logged_repo_pool))
        doc_repo = PgDocumentRepository(pool=cast(Any, logged_repo_pool))
        parser = MarkdownAndTextParser()
        embedder = OpenAICompatEmbedder(
            base_url=cfg.EMBED_BASE_URL, api_key=cfg.EMBED_API_KEY,
            model=cfg.EMBED_MODEL, dim=cfg.EMBED_DIM,
            batch_size=cfg.EMBED_BATCH_SIZE, max_concurrency=cfg.EMBED_MAX_CONCURRENCY,
            max_retries=cfg.EMBED_MAX_RETRIES,
            request_timeout=cfg.EMBED_REQUEST_TIMEOUT,
            connect_timeout=cfg.EMBED_CONNECT_TIMEOUT,
            retry_backoff_base=cfg.EMBED_RETRY_BACKOFF_BASE,
        )

        keyword_store = None
        if cfg.ES_ENABLED:
            keyword_store = ESKeywordSearchProvider(
                url=cfg.ELASTICSEARCH_URL, index=cfg.ELASTICSEARCH_INDEX,
                request_timeout=cfg.ELASTICSEARCH_REQUEST_TIMEOUT,
            )
            try:
                await keyword_store.connect()
                await keyword_store.ensure_index()
            except Exception:
                keyword_store = None

        indexing_svc = IndexingService(
            doc_repo=doc_repo, parser=parser, embedder=embedder,
            chunker=heading_aware_split, store=store,
            keyword_store=keyword_store, es_enabled=cfg.ES_ENABLED,
            chunk_max_chars=cfg.CHUNK_MAX_CHARS,
            chunk_overlap=cfg.CHUNK_OVERLAP,
        )

        # 将连接的资源挂到 indexing_svc 上以便清理
        indexing_svc._store_pool = store_pool  # type: ignore[attr-defined]
        indexing_svc._repo_pool = repo_pool  # type: ignore[attr-defined]
        indexing_svc._embedder = embedder  # type: ignore[attr-defined]
        indexing_svc._keyword_store = keyword_store  # type: ignore[attr-defined]

        return indexing_svc, doc_repo, kb_repo

    return asyncio.run(_async_build())
```

- [ ] **Step 2: 重构 UploadDocumentUseCase — 拆分流水线**

将 `UploadDocumentUseCase.execute` 的前半部分（步骤 1-4: 校验 + doc_id + 去重）保留，步骤 5-10（解析→分块→嵌入→双写）移除，改为：

```python
    async def execute(
        self,
        kb_id: str,
        tenant_id: str,
        file_content: bytes,
        filename: str,
        content_type: str,
    ) -> UploadResult:
        # Steps 1-4 unchanged: size check, ext check, KB check, dedup
        # ... (keep existing code lines 67-138) ...

        # Step 5: Create document record with content stored
        text_content = file_content.decode("utf-8", errors="replace")
        doc = await self._doc_repo.create(
            doc_id=doc_id,
            kb_id=kb_id,
            filename=filename,
            file_hash=file_hash,
            file_size=len(file_content),
            content_type=content_type,
            content=text_content,
        )

        # Step 6: Submit async indexing task
        from ragnexus.tasks.indexing import index_document_task
        index_document_task.delay(doc_id)

        logger.info("索引任务已投递", extra={
            "event_type": "BIZ_EVENT",
            "event": "index_task_queued",
            "doc_id": doc_id,
            "kb_id": kb_id,
        })

        return UploadResult(
            doc_id=doc_id,
            kb_id=kb_id,
            status=DocStatus.PROCESSING,
            chunks=[],
            chunk_count=0,
        )
```

- [ ] **Step 3: 在 `__init__` 中添加 `doc_repo: DocumentPort` 参数**

```python
    def __init__(
        self,
        kb_repo: KnowledgeBasePort,
        doc_repo: DocumentPort,  # 新增
        ...
    ) -> None:
        self._doc_repo = doc_repo
```

- [ ] **Step 4: 更新 composition.py 中的 UploadDocumentUseCase 构造**

将 `composition.py` 中 `upload_doc_uc = UploadDocumentUseCase(...)` 调用添加 `doc_repo=document_repo` 参数。

同时更新 `upload_doc_router.py` 的返回体包含 `status`：

```python
        return {
            "code": 0,
            "data": {
                "doc_id": result.doc_id,
                "kb_id": result.kb_id,
                "status": result.status.name.lower(),  # "processing"
                "chunk_count": result.chunk_count,
            },
            "message": "ok",
        }
```

---

### Task 3.5: purge_document_chunks 工具方法

**Files:**
- Modify: `src/ragnexus/application/indexing_service.py`（添加静态方法）
- 或 Create: `src/ragnexus/application/purge_utils.py`

- [ ] **Step 1: 在 `IndexingService` 中添加静态方法（或在 `purge_utils.py` 中定义）**

推荐在 `indexing_service.py` 末尾添加：

```python
async def purge_document_chunks(
    doc_id: str,
    store: VectorStorePort,
    keyword_store: KeywordSearchPort | None = None,
) -> None:
    """清理文档的向量和关键词索引。

    PG 端：documents 表 ON DELETE CASCADE 自动清理 chunks。
    ES 端：需显式按 doc_id 删除。
    """
    if keyword_store is not None:
        try:
            await keyword_store.delete_by_document(doc_id)
        except Exception as exc:
            logger.warning("ES 清理文档 chunks 失败", extra={
                "doc_id": doc_id, "error": str(exc),
            })
```

- [ ] **Step 2: 在 KeywordSearchPort 中添加 `delete_by_document` 方法**

编辑 `src/ragnexus/domain/ports.py`，在 `KeywordSearchPort` 的 `delete` 方法后添加：

```python
    async def delete_by_document(self, doc_id: str) -> None:
        """从关键词索引删除指定文档的所有 chunk。"""
        ...
```

- [ ] **Step 3: 在 ESKeywordSearchProvider 中实现 `delete_by_document`**

编辑 `src/ragnexus/adapters/keyword_search/elasticsearch.py`，添加方法：

```python
    async def delete_by_document(self, doc_id: str) -> None:
        """按文档 ID 删除 ES 中所有相关 chunk。"""
        try:
            await self._client.delete_by_query(
                index=self._index,
                body={"query": {"term": {"doc_id": doc_id}}},
            )
        except Exception:
            logger.warning("ES delete_by_document 失败", extra={"doc_id": doc_id})
```

---

### Task 3.6: SynonymSyncUploadUseCase 触发时机调整

**Files:**
- Modify: `src/ragnexus/composition.py`（SynonymSyncUploadUseCase 类）

- [ ] **Step 1: 修改策略 — 上传后暂不触发词表同步**

当前 `SynonymSyncUploadUseCase.execute` 在上传完成后立即 fire-and-forget 词表同步。异步索引后，文档内容尚未索引，词表同步应推迟到索引完成后。

修改 `SynonymSyncUploadUseCase.execute`：

```python
    async def execute(self, kb_id, tenant_id, file_content, filename, content_type):
        result = await self._inner.execute(
            kb_id=kb_id, tenant_id=tenant_id,
            file_content=file_content, filename=filename,
            content_type=content_type,
        )
        # 异步索引后：文档尚未完成索引时跳过词表同步
        # 词表同步将在 IndexingService.execute 成功后触发
        if result.status == DocStatus.SUCCESS:
            if self._llm is not None:
                import asyncio as _asyncio
                _asyncio.create_task(self._sync_synonyms(kb_id))
        return result
```

- [ ] **Step 2: 在 IndexingService.execute 成功后触发词表同步**

在 `indexing_service.py` 的 `execute()` 方法 SUCCESS 路径末尾添加 fire-and-forget 词表同步。或者此步骤通过在 `composition.py` 中的装饰器模式实现——在 Worker 进程中不适用装饰器，改为在 IndexingService 中直接集成。

由于 Worker 进程独立于 API 进程，词表同步逻辑需在 IndexingService 中直接调用（或通过回调）。推荐方案：在 IndexingService 的 `execute()` 中添加 `synonym_sync_callback: Callable | None = None` 参数，SUCCESS 后调用。

---

## Phase 4: 运维 API (Tasks 4.1–4.7)

### Task 4.1: GET /v1/documents/{doc_id} 路由

**Files:**
- Create: `src/ragnexus/application/document_query_uc.py`
- Create: `src/ragnexus/adapters/http/document_router.py`（集中管理文档路由）

- [ ] **Step 1: 创建 DocumentQueryUseCase**

```python
"""DocumentQueryUseCase — 查询单个文档详情。"""

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import Document
from ragnexus.domain.ports import DocumentPort, KnowledgeBasePort


class DocumentQueryUseCase:
    def __init__(self, doc_repo: DocumentPort, kb_repo: KnowledgeBasePort) -> None:
        self._doc_repo = doc_repo
        self._kb_repo = kb_repo

    async def execute(self, doc_id: str, tenant_id: str) -> Document:
        doc = await self._doc_repo.get(doc_id)
        if doc is None:
            raise AppError(ErrorCode.NOT_FOUND, "文档不存在")
        # 校验租户归属
        kb = await self._kb_repo.get(doc.kb_id)
        if kb is None or kb.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "文档不存在")
        return doc
```

- [ ] **Step 2: 创建 document_router.py**

```python
"""文档运维路由 — GET/DELETE/reindex。"""

from fastapi import APIRouter, Depends

from ragnexus.core.auth import TenantContext


def create_document_router(uc_query, uc_delete, uc_reindex, get_current_tenant) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/documents/{doc_id}")
    async def get_document(
        doc_id: str,
        current_tenant: TenantContext = Depends(get_current_tenant),
    ):
        doc = await uc_query.execute(doc_id, current_tenant.tenant_id)
        return {
            "code": 0,
            "data": {
                "doc_id": doc.doc_id,
                "kb_id": doc.kb_id,
                "filename": doc.filename,
                "file_hash": doc.file_hash,
                "file_size": doc.file_size,
                "content_type": doc.content_type,
                "status": doc.status.name.lower(),
                "chunk_count": doc.chunk_count,
                "error_message": doc.error_message,
                "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
                "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
            },
            "message": "ok",
        }

    return router
```

---

### Task 4.2: DELETE /v1/documents/{doc_id} 路由

**Files:**
- Create: `src/ragnexus/application/document_delete_uc.py`
- Modify: `src/ragnexus/adapters/http/document_router.py`

- [ ] **Step 1: 创建 DocumentDeleteUseCase**

```python
"""DocumentDeleteUseCase — 删除文档。"""

from ragnexus.application.indexing_service import purge_document_chunks
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import DocStatus
from ragnexus.domain.ports import (
    DocumentPort,
    KnowledgeBasePort,
    KeywordSearchPort,
    VectorStorePort,
)


class DocumentDeleteUseCase:
    def __init__(
        self,
        doc_repo: DocumentPort,
        kb_repo: KnowledgeBasePort,
        store: VectorStorePort,
        keyword_store: KeywordSearchPort | None = None,
    ) -> None:
        self._doc_repo = doc_repo
        self._kb_repo = kb_repo
        self._store = store
        self._keyword_store = keyword_store

    async def execute(self, doc_id: str, tenant_id: str) -> None:
        doc = await self._doc_repo.get(doc_id)
        if doc is None:
            raise AppError(ErrorCode.NOT_FOUND, "文档不存在")

        # 校验租户归属
        kb = await self._kb_repo.get(doc.kb_id)
        if kb is None or kb.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "文档不存在")

        # PROCESSING 时拒绝删除
        if doc.status == DocStatus.PROCESSING:
            raise AppError(
                ErrorCode.RESOURCE_CONFLICT,
                "文档正在索引中，无法删除",
                errors=[{"field": "status", "reason": "文档状态为 PROCESSING"}],
            )

        # 清理 ES 索引
        await purge_document_chunks(doc_id, self._store, self._keyword_store)

        # 删除文档（PG CASCADE 自动清理 chunks）
        await self._doc_repo.delete(doc_id)
```

- [ ] **Step 2: 在 document_router.py 中添加 DELETE 端点**

```python
    @router.delete("/v1/documents/{doc_id}")
    async def delete_document(
        doc_id: str,
        current_tenant: TenantContext = Depends(get_current_tenant),
    ):
        await uc_delete.execute(doc_id, current_tenant.tenant_id)
        return {"code": 0, "data": None, "message": "ok"}
```

---

### Task 4.3: POST /v1/documents/{doc_id}/reindex 路由

**Files:**
- Create: `src/ragnexus/application/document_reindex_uc.py`
- Modify: 同上 document_router.py

- [ ] **Step 1: 创建 DocumentReindexUseCase**

```python
"""DocumentReindexUseCase — 重新索引文档（仅 FAILED 状态允许）。"""

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import DocStatus
from ragnexus.domain.ports import DocumentPort, KnowledgeBasePort
from ragnexus.tasks.indexing import index_document_task


class DocumentReindexUseCase:
    def __init__(self, doc_repo: DocumentPort, kb_repo: KnowledgeBasePort) -> None:
        self._doc_repo = doc_repo
        self._kb_repo = kb_repo

    async def execute(self, doc_id: str, tenant_id: str) -> dict:
        doc = await self._doc_repo.get(doc_id)
        if doc is None:
            raise AppError(ErrorCode.NOT_FOUND, "文档不存在")

        kb = await self._kb_repo.get(doc.kb_id)
        if kb is None or kb.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "文档不存在")

        if doc.status != DocStatus.FAILED:
            raise AppError(
                ErrorCode.RESOURCE_CONFLICT,
                "仅 FAILED 状态的文档允许重新索引",
                errors=[{"field": "status", "reason": f"当前状态: {doc.status.name}"}],
            )

        # 重置为 PROCESSING
        await self._doc_repo.update_status(doc_id, status=DocStatus.PROCESSING, error_message=None)
        index_document_task.delay(doc_id)

        return {"doc_id": doc_id, "status": "processing"}
```

- [ ] **Step 2: 在 document_router.py 中添加 POST 端点**

```python
    @router.post("/v1/documents/{doc_id}/reindex")
    async def reindex_document(
        doc_id: str,
        current_tenant: TenantContext = Depends(get_current_tenant),
    ):
        result = await uc_reindex.execute(doc_id, current_tenant.tenant_id)
        return {"code": 0, "data": result, "message": "ok"}
```

- [ ] **Step 3: 更新 document_router.py 的工厂函数签名**

改为接收三个 use case：

```python
def create_document_router(uc_query, uc_delete, uc_reindex, get_current_tenant) -> APIRouter:
```

---

### Task 4.4–4.6: KB CRUD 路由

**Files:**
- Create: `src/ragnexus/application/kb_detail_uc.py`
- Create: `src/ragnexus/application/kb_update_uc.py`
- Create: `src/ragnexus/application/kb_delete_uc.py`
- Create: `src/ragnexus/adapters/http/kb_router.py`（集中 KB 运维路由）

- [ ] **Step 1: KnowledgeBaseDetailUseCase**

```python
"""KnowledgeBaseDetailUseCase — 获取知识库完整详情。"""

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import KnowledgeBase
from ragnexus.domain.ports import KnowledgeBasePort


class KnowledgeBaseDetailUseCase:
    def __init__(self, kb_repo: KnowledgeBasePort) -> None:
        self._kb_repo = kb_repo

    async def execute(self, kb_id: str, tenant_id: str) -> KnowledgeBase:
        kb = await self._kb_repo.get(kb_id)
        if kb is None or kb.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "知识库不存在")
        return kb
```

- [ ] **Step 2: KnowledgeBaseUpdateUseCase**

```python
"""KnowledgeBaseUpdateUseCase — 更新知识库字段。"""

import json

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import KnowledgeBase
from ragnexus.domain.ports import KnowledgeBasePort


class KnowledgeBaseUpdateUseCase:
    def __init__(self, kb_repo: KnowledgeBasePort) -> None:
        self._kb_repo = kb_repo

    async def execute(
        self,
        kb_id: str,
        tenant_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        settings: dict | None = None,
    ) -> KnowledgeBase:
        kb = await self._kb_repo.get(kb_id)
        if kb is None or kb.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "知识库不存在")

        # settings 合法性校验
        if settings is not None:
            if not isinstance(settings, dict):
                raise AppError(ErrorCode.PARAM_ERROR, "settings 必须是 JSON 对象")
            # 可扩展: 校验 settings 内字段类型

        return await self._kb_repo.update(
            kb_id, name=name, description=description, settings=settings
        )
```

- [ ] **Step 3: KnowledgeBaseDeleteUseCase**

```python
"""KnowledgeBaseDeleteUseCase — 删除知识库。"""

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.ports import (
    DocumentPort,
    KnowledgeBasePort,
    KeywordSearchPort,
    VectorStorePort,
)


class KnowledgeBaseDeleteUseCase:
    def __init__(
        self,
        kb_repo: KnowledgeBasePort,
        doc_repo: DocumentPort,
        store: VectorStorePort,
        keyword_store: KeywordSearchPort | None = None,
    ) -> None:
        self._kb_repo = kb_repo
        self._doc_repo = doc_repo
        self._store = store
        self._keyword_store = keyword_store

    async def execute(self, kb_id: str, tenant_id: str) -> None:
        kb = await self._kb_repo.get(kb_id)
        if kb is None or kb.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "知识库不存在")

        # 检查是否有 PROCESSING 文档
        if await self._doc_repo.has_processing(kb_id):
            raise AppError(
                ErrorCode.RESOURCE_CONFLICT,
                "知识库下有文档正在索引中，无法删除",
                errors=[{"field": "kb_id", "reason": "存在 PROCESSING 状态的文档"}],
            )

        # 清理 ES（可选 — PG CASCADE 处理 chunks，ES 需显式）
        if self._keyword_store is not None:
            docs = await self._doc_repo.get_by_kb(kb_id)
            for doc in docs:
                try:
                    await self._keyword_store.delete_by_document(doc.doc_id)
                except Exception:
                    pass

        # 删除文档（CASCADE 清理 chunks）
        await self._doc_repo.delete_by_kb(kb_id)

        # 删除 KB
        await self._kb_repo.delete(kb_id)
```

- [ ] **Step 4: 创建 kb_router.py**

```python
"""知识库运维路由工厂。"""

from fastapi import APIRouter, Depends, Body

from ragnexus.core.auth import TenantContext


def create_kb_router(uc_detail, uc_update, uc_delete, get_current_tenant) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/knowledge-bases/{kb_id}")
    async def get_kb(
        kb_id: str,
        current_tenant: TenantContext = Depends(get_current_tenant),
    ):
        kb = await uc_detail.execute(kb_id, current_tenant.tenant_id)
        return {
            "code": 0,
            "data": {
                "id": kb.id,
                "name": kb.name,
                "description": kb.description,
                "settings": kb.settings,
                "tenant_id": kb.tenant_id,
                "created_at": kb.created_at.isoformat(),
            },
            "message": "ok",
        }

    @router.patch("/v1/knowledge-bases/{kb_id}")
    async def update_kb(
        kb_id: str,
        name: str | None = Body(None),
        description: str | None = Body(None),
        settings: dict | None = Body(None),
        current_tenant: TenantContext = Depends(get_current_tenant),
    ):
        kb = await uc_update.execute(
            kb_id, current_tenant.tenant_id,
            name=name, description=description, settings=settings,
        )
        return {
            "code": 0,
            "data": {
                "id": kb.id, "name": kb.name,
                "description": kb.description,
                "settings": kb.settings,
            },
            "message": "ok",
        }

    @router.delete("/v1/knowledge-bases/{kb_id}")
    async def delete_kb(
        kb_id: str,
        current_tenant: TenantContext = Depends(get_current_tenant),
    ):
        await uc_delete.execute(kb_id, current_tenant.tenant_id)
        return {"code": 0, "data": None, "message": "ok"}

    return router
```

---

### Task 4.7: tree 接口适配

**Files:**
- Modify: `src/ragnexus/adapters/knowledge_base/pg.py`（`list_with_documents` 方法）

- [ ] **Step 1: 更新 list_with_documents SQL 查询**

将 SQL 查询中的 `d.chunk_count` 改为包含 status 和 error_message：

```sql
SELECT kb.tenant_id, kb.id AS kb_id, kb.name, kb.description, kb.created_at,
       d.doc_id, d.filename, d.uploaded_at, d.chunk_count, d.status, d.error_message
FROM knowledge_bases kb
LEFT JOIN documents d ON d.kb_id = kb.id
WHERE kb.tenant_id = $1 AND kb.name ILIKE $2
ORDER BY kb.tenant_id, kb.created_at DESC, d.uploaded_at DESC
```

- [ ] **Step 2: 更新 DocNode 构造**

将 `status="completed"` 替换为从 DB 读取的实际状态：

```python
# 状态映射: DocStatus IntEnum → tree API 字符串
_status_map = {1: "success", 2: "processing", 3: "failed"}

DocNode(
    doc_id=row["doc_id"],
    filename=row["filename"],
    status=_status_map.get(row["status"], "unknown"),
    uploaded_at=row["uploaded_at"].isoformat(),
    error_message=row["error_message"],
)
```

- [ ] **Step 3: 更新 KBNode 构造，包含 description**

```python
KBNode(
    kb_id=kid,
    name=info["name"],
    description=info.get("description", ""),
    ...
)
```

---

## Phase 5: 前端适配 (Tasks 5.1–5.9)

> **注意：** 前端计划为概要性质——前端项目的目录结构和组件框架未知。实施时需先探索前端代码库找到确切文件路径。

### Task 5.1: types/api.ts — 新增类型

- [ ] 新增 `DocStatus` 枚举: `PROCESSING = 'processing'`, `SUCCESS = 'success'`, `FAILED = 'failed'`
- [ ] 新增 `DocumentDetail` 接口: `doc_id, kb_id, filename, status, chunk_count, error_message, uploaded_at, updated_at`
- [ ] 新增 `UpdateKBRequest` 接口: `name?, description?, settings?`

### Task 5.2: documentService.ts — 新增 API 调用

- [ ] 新增 `deleteDocument(docId: string): Promise<void>`
- [ ] 新增 `reindexDocument(docId: string): Promise<{doc_id, status}>`

### Task 5.3: knowledgeBaseService.ts — 新增 API 调用

- [ ] 新增 `fetchDetail(kbId: string): Promise<KnowledgeBaseDetail>`
- [ ] 新增 `updateKB(kbId: string, req: UpdateKBRequest): Promise<void>`
- [ ] 新增 `deleteKB(kbId: string): Promise<void>`

### Task 5.4: 上传页适配

- [ ] 上传响应处理后显示 Toast "已提交，正在后台索引..."
- [ ] 返回的 `status: "processing"` 正确展示

### Task 5.5: 列表页 — StatusBadge + 轮询

- [ ] 创建 `StatusBadge` 组件：黄=PROCESSING, 绿=SUCCESS, 红=FAILED
- [ ] PROCESSING 状态的文档行：每 3 秒轮询 `GET /v1/documents/{doc_id}` 直到状态变化
- [ ] 轮询最大次数限制（60 次 ≈ 3 分钟），超时显示超时提示

### Task 5.6: 列表页 — 操作按钮

- [ ] 文档行：删除按钮（SUCCESS/FAILED 时显示）
- [ ] 文档行：重试按钮（仅 FAILED 时显示）
- [ ] KB 行：编辑按钮 + 删除按钮

### Task 5.7: ConfirmDialog 组件

- [ ] 创建复用组件 `ConfirmDialog`（Props: `title, message, onConfirm, onCancel, loading?`）
- [ ] 删文档确认："确定删除文档 xxx 吗？"
- [ ] 删 KB 确认："确定删除知识库 xxx 吗？此操作不可撤销。"

### Task 5.8: EditKnowledgeBaseDialog 组件

- [ ] 创建 `EditKnowledgeBaseDialog` 组件
- [ ] name Input（必填）
- [ ] description Textarea
- [ ] settings Textarea（等宽字体 `font-mono`）

### Task 5.9: 集成测试

- [ ] 三页导航正常（上传页 → 列表页 → KB 编辑页）
- [ ] 完整操作路径：上传 → 列表轮询 → 查看详情 → 删除

---

## Phase 6: 测试与文档 (Tasks 6.1–6.7)

### Task 6.1: 单元测试 — IndexingService、DocumentRepository、KnowledgeBaseRepository

**Files:**
- Create: `tests/unit/application/test_indexing_service.py`
- Create: `tests/unit/adapters/test_document_repo.py`
- Modify: `tests/unit/adapters/test_kb_repo.py`

- [ ] **Step 1: TestIndexingService**

```python
"""Tests for IndexingService — TDD.  """

import pytest
from unittest.mock import AsyncMock, MagicMock

from ragnexus.application.indexing_service import IndexingService
from ragnexus.domain.models import DocStatus, Document


@pytest.fixture
def mock_doc_repo():
    repo = MagicMock()
    repo.get = AsyncMock()
    repo.update_status = AsyncMock()
    return repo


class TestIndexingServiceExecute:
    @pytest.mark.asyncio
    async def test_execute_success(self, mock_doc_repo):
        """正常索引流程：PROCESSING → SUCCESS。"""
        # Arrange
        mock_doc_repo.get.return_value = Document(
            doc_id="doc_test", kb_id="kb_test",
            filename="test.md", file_hash="abc",
            file_size=100, content_type="text/markdown",
            content="# Hello", status=DocStatus.PROCESSING,
        )
        # 需要 mock parser, chunker, embedder, store ...
        # (完整 mock 略，遵循 test_upload_doc.py 模式)

    @pytest.mark.asyncio
    async def test_execute_idempotent(self, mock_doc_repo):
        """幂等保护：status != PROCESSING 时直接返回。"""
        mock_doc_repo.get.return_value = Document(
            doc_id="doc_test", kb_id="kb_test",
            filename="test.md", file_hash="abc",
            file_size=100, content_type="text/markdown",
            content="# Hello", status=DocStatus.SUCCESS,
        )
        # execute 应该直接 return，不调用 update_status
        ...

    @pytest.mark.asyncio
    async def test_execute_doc_not_found(self, mock_doc_repo):
        """文档不存在时直接返回。"""
        mock_doc_repo.get.return_value = None
        ...
```

- [ ] **Step 2: TestPgDocumentRepository**

```python
"""Tests for PgDocumentRepository — TDD."""
# 参考 test_kb_repo.py 的模式: AsyncMock pool + assert_awaited_once_with
# 覆盖: create / get / update_status / delete / has_processing / get_by_kb
```

- [ ] **Step 3: TestPgKnowledgeBaseRepository — 扩展 update/delete**

在 `tests/unit/adapters/test_kb_repo.py` 中添加测试类：

```python
class TestUpdate: ...
class TestDelete: ...
```

---

### Task 6.2: 集成测试 — 异步上传完整链路

**Files:**
- Create: `tests/integration/test_async_upload.py`

- [ ] **Step 1: 创建测试**

```python
"""集成测试：异步上传 → 轮询 → 检索命中。"""

import asyncio
import pytest

from ragnexus.application.indexing_service import IndexingService


@pytest.mark.integration
class TestAsyncUploadFullChain:
    @pytest.mark.asyncio
    async def test_upload_then_poll_then_search(self, pg_pool, httpx_mock):
        """完整链路：创建 KB → 上传文档 → 轮询状态 → 验证 SUCCESS → 检索命中。"""
        # Arrange: 创建 KB
        # Act: 上传文档
        # Assert: 返回 status=processing
        # Act: 轮询 GET /v1/documents/{doc_id}
        # Assert: 最终 status=success, chunk_count > 0
        # Act: 检索
        # Assert: 命中包含上传的文档
        ...
```

---

### Task 6.3: 集成测试 — ES 不可用 → FAILED → 恢复 → reindex → SUCCESS

**Files:**
- 同上 `tests/integration/test_async_upload.py`

**关键断言：**
- ES 停用后上传 → 文档 status=FAILED
- ES 恢复后 reindex → status=SUCCESS

---

### Task 6.4: 集成测试 — knowledge-base CRUD

**Files:**
- Create: `tests/integration/test_kb_crud.py`

- [ ] 覆盖 GET/PATCH/DELETE
- [ ] PATCH 非法 settings → PARAM_ERROR
- [ ] 跨租户 PATCH/DELETE → NOT_FOUND

---

### Task 6.5: 集成测试 — 跨租户隔离

**Files:**
- 同上 `tests/integration/test_kb_crud.py`

- [ ] GET document 跨租户 → NOT_FOUND
- [ ] DELETE document 跨租户 → NOT_FOUND
- [ ] POST reindex 跨租户 → NOT_FOUND
- [ ] GET/PATCH/DELETE KB 跨租户 → NOT_FOUND

---

### Task 6.6: E2E 测试 — PROCESSING 文档 DELETE 被拒绝

**Files:**
- Create: `tests/e2e/test_processing_rejections.py`

**E2E 模式**（参考 `tests/e2e/test_smoke.py`）：
```python
from fastapi.testclient import TestClient

def test_delete_processing_document_rejected(client: TestClient):
    """PROCESSING 状态的文档删除应返回 409。"""
    ...
```

---

### Task 6.7: README.md 更新

**Files:**
- Modify: `README.md`

- [ ] 在"快速启动"部分添加 Worker 启动命令

```bash
# 启动 Worker
celery -A src.ragnexus.celery_app worker --loglevel=info --concurrency=2

# 启动 Beat (超时检测)
celery -A src.ragnexus.celery_app beat --loglevel=info
```

- [ ] 在"架构"部分添加异步索引说明

---

## 执行顺序与依赖关系

```
Phase 1 (基础设施)
├── 1.1 docker-compose    ← 无依赖
├── 1.2 pyproject.toml    ← 无依赖
├── 1.3 Settings          ← 无依赖，可并行
├── 1.4 Alembic migration ← 无依赖
├── 1.5 schema.sql        ← 1.4 之后
└── 1.1-1.4 全部可并行

Phase 2 (领域层)
├── 2.1 DocStatus + Document  ← 无依赖
├── 2.2 UploadResult +status  ← 2.1
├── 2.3 DocNode +error_msg    ← 2.1
├── 2.4 DocumentPort          ← 2.1
├── 2.5 KnowledgeBasePort ext ← 无依赖
├── 2.6 PgDocumentRepository  ← 2.1, 2.4
├── 2.7 PgKBRepository ext    ← 2.5
└── 2.8 composition.py DI     ← 2.6, 2.7 (占位注入，不改变行为)

Phase 3 (异步索引核心) ← 依赖 Phase 1 + 2
├── 3.1 celery_app.py    ← 1.2, 1.3
├── 3.2 indexing_service  ← 2.1, 2.4, 2.6
├── 3.3 tasks/indexing.py ← 3.1, 3.2
├── 3.4 重构 Upload + di  ← 2.8, 3.1, 3.3
├── 3.5 purge_chunks      ← 2.4, 2.6
└── 3.6 词表同步调整      ← 3.4

Phase 4 (运维 API) ← 依赖 Phase 2 + 3
├── 4.1 GET /documents/{id}  ← 2.4, 2.6
├── 4.2 DELETE /documents    ← 4.1, 3.5
├── 4.3 POST reindex         ← 4.1, 3.3
├── 4.4 GET /kbs/{id}        ← 2.5
├── 4.5 PATCH /kbs/{id}      ← 2.5, 2.7
├── 4.6 DELETE /kbs/{id}     ← 2.5, 2.7
└── 4.7 tree 适配            ← 2.3, 2.7

Phase 5 (前端) ← 依赖 Phase 4 (API 就绪)
全部串行（通常一个开发者完成）

Phase 6 (测试与文档) ← 依赖 Phase 1-4
├── 6.1 单元测试   ← Phase 2 + 3 完成后
├── 6.2-6.5 集成   ← Phase 4 完成后
├── 6.6 E2E         ← Phase 4 + 5 完成后
└── 6.7 README      ← 全部完成后
```

---

## 验证清单

- [ ] `docker compose up` 全部 6 个服务正常启动（redis, worker, beat, app, db, elasticsearch）
- [ ] `POST /v1/documents:upload` 返回 `status: "processing"` 而非同步结果
- [ ] Worker 日志显示 `document_indexed` 事件
- [ ] `GET /v1/documents/{doc_id}` 返回最终 `status: "success"` + chunk_count > 0
- [ ] ES 停用后上传 → `status: "failed"`, 恢复后 reindex → `status: "success"`
- [ ] PROCESSING 文档删除返回 409
- [ ] 库有 PROCESSING 文档时删除 KB 返回 409
- [ ] 跨租户访问返回 404（不泄露存在性）
- [ ] 前端三状态 Badge 正确渲染
- [ ] `pytest -m "not integration and not e2e"` 全部通过
- [ ] `pytest -m integration` 全部通过
- [ ] `pytest -m e2e` 全部通过
''')
print('plan written successfully')
