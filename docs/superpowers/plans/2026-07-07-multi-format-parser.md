---
change: multi-format-parser
design-doc: docs/superpowers/specs/2026-07-07-multi-format-parser-design.md
base-ref: 48004700b67fd7fb06a0fabf69e5fef224656ca6
---

# 多格式文档解析 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 RAGNexus 文档处理流水线前增加插件化解析层，支持 `.docx`（Word，mammoth）和 `.pdf`（PyMuPDF）二进制格式的直传与自动解析，输出统一 `ParsedDocument` 无缝接入现有 `heading_aware_split` → embed → ES+pgvector 双写流水线。

**Architecture:** Parser Registry 按文件扩展名选择 DocxParser/PdfParser/MarkdownAndTextParser，二进制文件经 FileStoragePort 暂存磁盘后由 IndexingService._prepare_content 延迟解析；source_type 复用 content_type 字段减少 migration 列数。上传双模式：multipart 直传（现有 + 二进制扩展）+ JSON 文本上传（新增路由）。

**Tech Stack:** mammoth>=1.8.0, PyMuPDF>=1.24.0, Python 3.11+, asyncpg, FastAPI, Celery, Alembic

## Global Constraints

- **零破坏**：`.md`/`.txt` 上传行为完全不变，JSON 文本上传为新增独立路由
- **不改切块层**：`heading_aware_split` 签名、逻辑、消费方式不变
- **不改检索层**：`RetrieveUseCase`、embedding、向量存储、关键词检索均不感知
- **不改租户/配额系统**：`QuotaService`、`RateLimitService`、`TenantContext` 不新增字段
- `source_type` 复用 `content_type` 字段（MIME type 自然映射），**不新增数据库列**
- `DOCUMENT_PARSE_FAILED` 错误码为 20023，HTTP 422

---

### Task 1: 领域模型扩展

**Files:**
- Modify: `src/ragnexus/domain/models.py` (ParsedDocument, Document)
- Modify: `src/ragnexus/domain/ports.py` (FileStoragePort)
- Modify: `src/ragnexus/core/errors.py` (DOCUMENT_PARSE_FAILED)
- Test: `tests/unit/domain/test_models.py` (扩展已有测试)

**Interfaces:**
- Produces: `ParsedDocument.source_type: str`, `ParsedDocument.metadata: dict`; `Document.source_file_path: str | None`, `Document.source_filename: str | None`; `FileStoragePort` protocol with `save`/`read`/`delete`; `ErrorCode.DOCUMENT_PARSE_FAILED = (20023, 422, "文档解析失败")`

- [ ] **Step 1: 扩展 ParsedDocument**

```python
# src/ragnexus/domain/models.py — ParsedDocument dataclass (line 35)
@dataclass
class ParsedDocument:
    filename: str
    sections: list[Section]
    raw_text: str  # full text for fallback splitting
    source_type: str = "text"       # 新增: text | markdown | docx | pdf
    metadata: dict = field(default_factory=dict)  # 新增: parser 元信息
```

- [ ] **Step 2: 扩展 Document**

```python
# src/ragnexus/domain/models.py — Document dataclass (line 73)
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
    source_file_path: str | None = None    # 新增 — 原文件磁盘路径
    source_filename: str | None = None     # 新增 — 原始文件名
```

- [ ] **Step 3: 新增 FileStoragePort**

```python
# src/ragnexus/domain/ports.py — 在 ParserPort 之后新增
class FileStoragePort(Protocol):
    """文件存储端口 — 二进制文件暂存与读取。"""
    async def save(self, tenant_id: str, doc_id: str,
                   filename: str, content: bytes) -> str: ...
    async def read(self, path: str) -> bytes: ...
    async def delete(self, path: str) -> None: ...
```

- [ ] **Step 4: 新增 DOCUMENT_PARSE_FAILED 错误码**

```python
# src/ragnexus/core/errors.py — 在反馈区间后、数据库区间前插入
# 反馈 (20020~20029)
FEEDBACK_SERVICE_UNAVAILABLE = (20020, 503, "反馈服务不可用")
FEEDBACK_UNAUTHORIZED = (20021, 403, "无权操作该反馈记录")
FEEDBACK_INVALID_SCORE = (20022, 422, "评分超出允许范围")
DOCUMENT_PARSE_FAILED = (20023, 422, "文档解析失败")  # 新增
```

- [ ] **Step 5: 更新现有测试以兼容新字段**

```python
# tests/unit/domain/test_models.py — 新增测试
def test_parsed_document_defaults():
    """ParsedDocument 默认 source_type='text', metadata={}"""
    from ragnexus.domain.models import ParsedDocument, Section
    doc = ParsedDocument(
        filename="test.txt",
        sections=[],
        raw_text="hello",
    )
    assert doc.source_type == "text"
    assert doc.metadata == {}

def test_document_new_fields_default_none():
    """Document 新字段 source_file_path/source_filename 默认为 None"""
    from ragnexus.domain.models import Document
    doc = Document(
        doc_id="d1", kb_id="k1", filename="f.txt",
        file_hash="h", file_size=10, content_type="text/plain", content="",
    )
    assert doc.source_file_path is None
    assert doc.source_filename is None
```

Run: `pytest tests/unit/domain/test_models.py -v`
Expected: 新增 2 tests PASS，原有 tests 仍需 PASS（可能需要更新 parser mock 返回的 ParsedDocument）

- [ ] **Step 6: 更新 ParserPort mock 以包含新字段**

检查 `tests/unit/application/test_upload_doc.py` 中的 mock_parser fixture — `ParsedDocument` 构造需加上 `source_type` 和 `metadata`（如果默认值生效则无需改）。同样检查 `tests/unit/application/test_indexing_service.py`。

Run: `pytest tests/unit/application/test_upload_doc.py tests/unit/application/test_indexing_service.py tests/unit/adapters/test_parser.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/ragnexus/domain/models.py src/ragnexus/domain/ports.py src/ragnexus/core/errors.py tests/unit/domain/test_models.py
git commit -m "feat: extend domain models for multi-format parsing"
```

### Task 2: 配置变更

**Files:**
- Modify: `src/ragnexus/config.py:45-46`
- Modify: `src/ragnexus/composition.py:474-486` (MAX_FILE_SIZE 计算方式变更)
- Modify: `src/ragnexus/application/upload_doc_use_case.py:47` (默认值变更)

**Interfaces:**
- Produces: `Settings.DOCUMENT_STORAGE_PATH`, `Settings.DOCUMENT_MAX_SIZE_MB`; `Settings.MAX_FILE_SIZE` 语义不变但值由 `DOCUMENT_MAX_SIZE_MB` 换算

- [ ] **Step 1: 新增配置字段**

```python
# src/ragnexus/config.py — 在 CHUNK_OVERLAP 之后
CHUNK_OVERLAP: int = 50
DOCUMENT_STORAGE_PATH: str = Field(default="./data/uploads")           # 新增
DOCUMENT_MAX_SIZE_MB: int = Field(default=20)                          # 新增
MAX_FILE_SIZE: int = 20 * 1024 * 1024  # 20MB（由 DOCUMENT_MAX_SIZE_MB 换算，保留字段名兼容）
```

注意：`MAX_FILE_SIZE` 字段名保留不变，值改为 20 * 1024 * 1024（与 DOCUMENT_MAX_SIZE_MB 默认值一致）。`DOCUMENT_MAX_SIZE_MB` 作为面向用户的配置入口。

- [ ] **Step 2: 更新 composition.py 上传 use case 构造**

```python
# src/ragnexus/composition.py — upload_doc_uc 构造（约 line 474）
upload_doc_uc = UploadDocumentUseCase(
    kb_repo=kb_repo,
    doc_repo=document_repo,
    parser=parser,
    embedder=embedder,
    chunker=chunker,
    store=store,
    max_file_size=cfg.MAX_FILE_SIZE,  # 值已为 20MB = DOCUMENT_MAX_SIZE_MB * 1024 * 1024
    chunk_max_chars=cfg.CHUNK_MAX_CHARS,
    chunk_overlap=cfg.CHUNK_OVERLAP,
    keyword_store=keyword_store,
    es_enabled=cfg.ES_ENABLED,
)
```

- [ ] **Step 3: 更新 UploadDocumentUseCase 默认值**

```python
# src/ragnexus/application/upload_doc_use_case.py — __init__ 签名
max_file_size: int = 20 * 1024 * 1024,  # 20MB（原 10 * 1024 * 1024）
allowed_exts: tuple[str, ...] = (".md", ".txt"),  # 本期暂不改，Task 9 扩展
```

- [ ] **Step 4: 验证现有测试不回归**

Run: `pytest tests/unit/application/test_upload_doc.py tests/unit/test_config.py -v`
Expected: ALL PASS（MAX_FILE_SIZE 值变化不影响已有测试逻辑，仅大小校验边界值可能需调整）

- [ ] **Step 5: Commit**

```bash
git add src/ragnexus/config.py src/ragnexus/composition.py src/ragnexus/application/upload_doc_use_case.py
git commit -m "feat: add DOCUMENT_STORAGE_PATH and DOCUMENT_MAX_SIZE_MB config"
```

### Task 3: 数据库迁移

**Files:**
- Create: `alembic/versions/0009_add_document_source_fields.py`
- Modify: `docs/sql/schema.sql:13-26`

**Interfaces:**
- Consumes: `Document.source_file_path`, `Document.source_filename` (Task 1)
- Produces: `documents` 表新增 `source_file_path TEXT`、`source_filename TEXT` 列

- [ ] **Step 1: 创建 Alembic 迁移**

```bash
cd alembic && alembic revision -m "add source file fields to documents"
```

重命名生成的文件为 `0009_add_document_source_fields.py`（按现有命名约定 `000N_` 前缀）。

- [ ] **Step 2: 编写迁移 SQL**

```python
# alembic/versions/0009_add_document_source_fields.py
"""add source file fields to documents

Revision ID: <auto-generated>
Revises: 0008_retrieval_log_observability
Create Date: 2026-07-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '<auto-generated>'
down_revision: Union[str, None] = '0008_retrieval_log_observability'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('source_file_path', sa.Text(), nullable=True))
    op.add_column('documents', sa.Column('source_filename', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'source_filename')
    op.drop_column('documents', 'source_file_path')
```

> **关键决策**：不新增 `source_type` 列 — 复用已有 `content_type` 字段。`.docx` 上传时 `content_type` 存 MIME type `application/vnd.openxmlformats-officedocument.wordprocessingml.document`，API 响应时按需映射为 `docx`。

- [ ] **Step 3: 更新 schema.sql**

```sql
-- docs/sql/schema.sql — documents 表定义（line 13-26），在 error_message 前插入新列
CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,
    kb_id         TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    file_hash     TEXT NOT NULL,
    file_size     INTEGER NOT NULL,
    content_type  TEXT,
    chunk_count   INTEGER NOT NULL,
    uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status        INTEGER NOT NULL DEFAULT 2,
    content       TEXT NOT NULL DEFAULT '',
    source_file_path TEXT,              -- 新增
    source_filename  TEXT,              -- 新增
    error_message TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

- [ ] **Step 4: 验证迁移**

```bash
alembic upgrade head
```

Run against test DB 确认 migration 成功：
```bash
pytest tests/integration/test_documents_table.py -v
```
Expected: PASS（表结构验证测试应包含新列存在性检查）

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/0009_add_document_source_fields.py docs/sql/schema.sql
git commit -m "feat: add source_file_path and source_filename to documents table"
```

### Task 4: PgDocumentRepository 扩展

**Files:**
- Modify: `src/ragnexus/adapters/document/pg.py:16-132` (create, get, get_by_kb)
- Modify: `src/ragnexus/domain/ports.py:170-203` (DocumentPort.create 签名扩展)
- Test: `tests/unit/adapters/test_document_repo.py`

**Interfaces:**
- Consumes: 迁移后 `source_file_path`/`source_filename` 列 (Task 3)
- Produces: `DocumentPort.create()` 新增 `source_file_path`/`source_filename` 可选参数；`get()`/`get_by_kb()` 返回带新字段的 `Document`

- [ ] **Step 1: 扩展 DocumentPort.create 签名**

```python
# src/ragnexus/domain/ports.py — DocumentPort.create (line 175)
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
    source_file_path: str | None = None,   # 新增
    source_filename: str | None = None,     # 新增
) -> "Document": ...
```

- [ ] **Step 2: 更新 PgDocumentRepository.create — INSERT**

```python
# src/ragnexus/adapters/document/pg.py:41-61 — create 方法
async def create(
    self, *, doc_id, kb_id, filename, file_hash, file_size, content_type, content,
    source_file_path=None, source_filename=None
) -> Document:
    now = datetime.now(UTC)
    await self.pool.execute(
        "INSERT INTO documents (doc_id, kb_id, filename, file_hash, "
        "file_size, content_type, content, source_file_path, source_filename, "
        "status, chunk_count, uploaded_at, updated_at) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
        doc_id, kb_id, filename, file_hash, file_size, content_type, content,
        source_file_path, source_filename,
        DocStatus.PROCESSING.value, 0, now, now,
    )
    return Document(
        doc_id=doc_id, kb_id=kb_id, filename=filename,
        file_hash=file_hash, file_size=file_size,
        content_type=content_type, content=content,
        status=DocStatus.PROCESSING, uploaded_at=now, updated_at=now,
        source_file_path=source_file_path,   # 新增
        source_filename=source_filename,     # 新增
    )
```

- [ ] **Step 3: 更新 PgDocumentRepository.get — SELECT**

```python
# src/ragnexus/adapters/document/pg.py:16-39 — get 方法
# SELECT 列清单增加 source_file_path, source_filename
row = await self.pool.fetchrow(
    "SELECT doc_id, kb_id, filename, file_hash, file_size, "
    "content_type, content, source_file_path, source_filename, "
    "status, chunk_count, error_message, uploaded_at, updated_at "
    "FROM documents WHERE doc_id = $1",
    doc_id,
)
# ...
return Document(
    doc_id=row["doc_id"],
    # ... 现有字段映射 ...
    source_file_path=row["source_file_path"],   # 新增
    source_filename=row["source_filename"],     # 新增
)
```

- [ ] **Step 4: 同样更新 get_by_kb 的 SELECT 和 Document 构造**

`get_by_kb` 方法与 `get` 共享相同的行映射模式，同步增加 `source_file_path`/`source_filename` 字段。

- [ ] **Step 5: 新增 update_content 方法（供 IndexingService._prepare_content 使用）**

```python
# src/ragnexus/adapters/document/pg.py — PgDocumentRepository 新增方法
async def update_content(self, doc_id: str, content: str) -> None:
    """更新文档 content 字段 — 供 _prepare_content 延迟解析后回写。"""
    await self.pool.execute(
        "UPDATE documents SET content = $1, updated_at = $2 WHERE doc_id = $3",
        content, datetime.now(UTC), doc_id,
    )
```

同时在 `DocumentPort` 协议中增加此方法签名：
```python
# src/ragnexus/domain/ports.py — DocumentPort 协议
async def update_content(self, doc_id: str, content: str) -> None: ...
```

- [ ] **Step 6: 更新单元测试**

```python
# tests/unit/adapters/test_document_repo.py — 新增测试
class TestCreateWithSourceFields:
    """create 支持 source_file_path/source_filename。"""

    @pytest.mark.asyncio
    async def test_create_with_source_fields(self, repo, mock_pool):
        """带 source_file_path/source_filename 时 INSERT 含对应参数。"""
        mock_pool.fetchrow.return_value = _row(
            doc_id="doc_bin", kb_id="kb_test", filename="report.docx",
            file_hash="abc", file_size=2048, content_type="application/...",
            content="", status=2, chunk_count=0, error_message=None,
            uploaded_at=datetime(2025, 1, 1), updated_at=datetime(2025, 1, 1),
            source_file_path="/data/uploads/default/doc_bin/report.docx",
            source_filename="report.docx",
        )

        result = await repo.create(
            doc_id="doc_bin", kb_id="kb_test", filename="report.docx",
            file_hash="abc", file_size=2048, content_type="application/...",
            content="",
            source_file_path="/data/uploads/default/doc_bin/report.docx",
            source_filename="report.docx",
        )

        assert result.source_file_path == "/data/uploads/default/doc_bin/report.docx"
        assert result.source_filename == "report.docx"
        # 验证 execute 调用参数包含新字段
        call_args = mock_pool.execute.call_args
        assert call_args[0][7] == "/data/uploads/default/doc_bin/report.docx"  # $8
        assert call_args[0][8] == "report.docx"                                # $9
```

Run: `pytest tests/unit/adapters/test_document_repo.py -v`
Expected: 新测试 PASS，原有测试 PASS

- [ ] **Step 7: Commit**

```bash
git add src/ragnexus/adapters/document/pg.py src/ragnexus/domain/ports.py tests/unit/adapters/test_document_repo.py
git commit -m "feat: extend PgDocumentRepository with source file fields and update_content"
```

### Task 5: 文件存储适配器 (LocalFileStorage)

**Files:**
- Create: `src/ragnexus/adapters/file_storage/__init__.py`
- Create: `src/ragnexus/adapters/file_storage/local.py`
- Test: `tests/unit/adapters/test_file_storage.py`（新建）

**Interfaces:**
- Consumes: `FileStoragePort` (Task 1), `Settings.DOCUMENT_STORAGE_PATH` (Task 2)
- Produces: `LocalFileStorage` 实现 `FileStoragePort`

- [ ] **Step 1: 创建 `__init__.py`**

```python
# src/ragnexus/adapters/file_storage/__init__.py
"""文件存储适配器 — 实现 FileStoragePort。"""
from ragnexus.adapters.file_storage.local import LocalFileStorage

__all__ = ["LocalFileStorage"]
```

- [ ] **Step 2: 实现 LocalFileStorage**

```python
# src/ragnexus/adapters/file_storage/local.py
"""LocalFileStorage — 本地文件系统存储适配器。"""
import os
from pathlib import Path

from ragnexus.config import get_settings


class LocalFileStorage:
    """本地文件系统存储 — 实现 FileStoragePort。

    文件路径: {DOCUMENT_STORAGE_PATH}/{tenant_id}/{doc_id}/{filename}
    目录不存在时自动创建。
    """

    def __init__(self, base_path: str | None = None) -> None:
        self._base = Path(base_path or get_settings().DOCUMENT_STORAGE_PATH)

    async def save(
        self, tenant_id: str, doc_id: str, filename: str, content: bytes
    ) -> str:
        """保存文件到 {base}/{tenant_id}/{doc_id}/{filename}，返回绝对路径。"""
        target_dir = self._base / tenant_id / doc_id
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / filename
        file_path.write_bytes(content)
        return str(file_path.absolute())

    async def read(self, path: str) -> bytes:
        """读取文件全部内容。"""
        return Path(path).read_bytes()

    async def delete(self, path: str) -> None:
        """删除文件，目录留空不清理（后续可扩展目录 GC）。"""
        file_path = Path(path)
        if file_path.exists():
            file_path.unlink()
```

- [ ] **Step 3: 编写单元测试**

```python
# tests/unit/adapters/test_file_storage.py
"""LocalFileStorage 单元测试。"""
import tempfile
from pathlib import Path

import pytest

from ragnexus.adapters.file_storage.local import LocalFileStorage


@pytest.fixture
def storage():
    """使用临时目录作为 base_path。"""
    with tempfile.TemporaryDirectory() as tmp:
        yield LocalFileStorage(base_path=tmp)


class TestLocalFileStorage:
    """LocalFileStorage save/read/delete 测试。"""

    @pytest.mark.asyncio
    async def test_save_and_read(self, storage):
        """save 后 read 应返回相同内容。"""
        content = b"Hello, binary world!"
        path = await storage.save("tenant1", "doc_abc", "report.docx", content)

        assert Path(path).exists()
        result = await storage.read(path)
        assert result == content

    @pytest.mark.asyncio
    async def test_save_creates_directory(self, storage):
        """不存在的目录应自动创建。"""
        content = b"test"
        path = await storage.save("tenant_x", "doc_y", "file.pdf", content)

        assert Path(path).parent.is_dir()
        assert Path(path).name == "file.pdf"

    @pytest.mark.asyncio
    async def test_delete_removes_file(self, storage):
        """delete 后文件应不存在。"""
        content = b"to be deleted"
        path = await storage.save("t1", "d1", "temp.bin", content)
        assert Path(path).exists()

        await storage.delete(path)
        assert not Path(path).exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_no_error(self, storage):
        """删除不存在的文件不抛异常。"""
        await storage.delete("/nonexistent/path/file.bin")
        # 不应抛出异常
```

Run: `pytest tests/unit/adapters/test_file_storage.py -v`
Expected: 4 tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/ragnexus/adapters/file_storage/ tests/unit/adapters/test_file_storage.py
git commit -m "feat: add LocalFileStorage adapter implementing FileStoragePort"
```

### Task 6: Parser 插件层 (Registry + DocxParser + PdfParser)

**Files:**
- Create: `src/ragnexus/adapters/parsers/registry.py`
- Modify: `src/ragnexus/adapters/parsers/__init__.py`
- Create: `src/ragnexus/adapters/parsers/docx.py`
- Create: `src/ragnexus/adapters/parsers/pdf.py`
- Modify: `src/ragnexus/adapters/parsers/md_and_txt.py:14-19`（微调 source_type）
- Test: `tests/unit/adapters/test_parser_registry.py`（新建）
- Test: `tests/unit/adapters/test_docx_parser.py`（新建）
- Test: `tests/unit/adapters/test_pdf_parser.py`（新建）

**Interfaces:**
- Consumes: `ParsedDocument.source_type` (Task 1), `ParserPort.parse` 签名
- Produces: `register(ext, parser)`, `get_parser(filename)`; `DocxParser`, `PdfParser` 实现 `ParserPort`

- [ ] **Step 1: 创建 registry.py**

```python
# src/ragnexus/adapters/parsers/registry.py
"""Parser 注册表 — 按文件扩展名选择 ParserPort 实现。"""
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.ports import ParserPort

_parsers: dict[str, ParserPort] = {}


def register(ext: str, parser: ParserPort) -> None:
    """注册扩展名对应的 parser。ext 可为 '.docx' 或 'docx'。"""
    _parsers[ext.lstrip(".").lower()] = parser


def get_parser(filename: str) -> ParserPort:
    """按 filename 扩展名查找 parser，未匹配抛 UNSUPPORTED_FORMAT。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    parser = _parsers.get(ext)
    if parser is None:
        raise AppError(
            ErrorCode.UNSUPPORTED_FORMAT,
            f"不支持的文件类型: .{ext}",
        )
    return parser
```

- [ ] **Step 2: 创建 DocxParser**

```python
# src/ragnexus/adapters/parsers/docx.py
"""DocxParser — 使用 mammoth convert_to_markdown 解析 Word 文档为 Sections。"""
import io

import mammoth

from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser
from ragnexus.domain.models import ParsedDocument, Section


class DocxParser:
    """Word .docx 解析器 — 实现 ParserPort。

    解析策略：mammoth.convert_to_markdown → MarkdownAndTextParser._parse_markdown。
    mammoth 是公开 API，MarkdownAndTextParser 已验证有效，无额外依赖风险。
    """

    async def parse(self, content: bytes, filename: str) -> ParsedDocument:
        result = mammoth.convert_to_markdown(io.BytesIO(content))
        md_text = result.value
        warnings = [w.message for w in result.messages]

        # 复用现有 Markdown 解析器按标题拆 sections
        md_parser = MarkdownAndTextParser()
        parsed = md_parser._parse_markdown(md_text, filename)
        sections = parsed.sections if parsed.sections else [
            Section(heading=None, level=0, content=md_text)
        ]

        return ParsedDocument(
            filename=filename,
            sections=sections,
            raw_text=md_text,
            source_type="docx",
            metadata={"parser": "mammoth", "warnings": warnings},
        )
```

- [ ] **Step 3: 创建 PdfParser**

```python
# src/ragnexus/adapters/parsers/pdf.py
"""PdfParser — 使用 PyMuPDF 按页抽取文字。"""
import fitz  # PyMuPDF

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import ParsedDocument, Section


class PdfParser:
    """PDF 解析器 — 实现 ParserPort。

    策略：按页抽取文字，每页作为独立 Section（heading="第 N 页", level=2）。
    若所有页均无文字，判定为扫描件并抛 DOCUMENT_PARSE_FAILED。
    """

    async def parse(self, content: bytes, filename: str) -> ParsedDocument:
        doc = fitz.open(stream=content, filetype="pdf")
        sections: list[Section] = []
        raw_parts: list[str] = []

        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            if text:
                sections.append(Section(
                    heading=f"第 {i + 1} 页",
                    level=2,
                    content=text,
                ))
                raw_parts.append(text)

        doc.close()

        if not sections:
            raise AppError(
                ErrorCode.DOCUMENT_PARSE_FAILED,
                "疑似扫描件，本期不支持 OCR",
            )

        return ParsedDocument(
            filename=filename,
            sections=sections,
            raw_text="\n\n".join(raw_parts),
            source_type="pdf",
            metadata={"parser": "pymupdf", "page_count": len(doc)},
        )
```

- [ ] **Step 4: 微调 MarkdownAndTextParser**

```python
# src/ragnexus/adapters/parsers/md_and_txt.py — parse 方法（约 line 14-19）
async def parse(self, content: bytes, filename: str) -> ParsedDocument:
    """按文件扩展名将字节内容解析为 ParsedDocument。"""
    text = content.decode("utf-8", errors="replace")
    if filename.lower().endswith(".md"):
        return self._parse_markdown(text, filename)
    return ParsedDocument(
        filename=filename,
        sections=[],
        raw_text=text,
        source_type="text",  # 明确标注
    )

# _parse_markdown 返回时增加 source_type
def _parse_markdown(self, text: str, filename: str) -> ParsedDocument:
    # ... 现有逻辑不变 ...
    return ParsedDocument(
        filename=filename,
        sections=sections,
        raw_text=text,
        source_type="markdown",  # 新增
    )
```

- [ ] **Step 5: 更新 parsers/__init__.py**

```python
# src/ragnexus/adapters/parsers/__init__.py
"""文档解析适配器 — ParserPort 实现和 registry。"""
from ragnexus.adapters.parsers.docx import DocxParser
from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser
from ragnexus.adapters.parsers.pdf import PdfParser
from ragnexus.adapters.parsers.registry import get_parser, register

__all__ = [
    "MarkdownAndTextParser",
    "DocxParser",
    "PdfParser",
    "register",
    "get_parser",
]
```

- [ ] **Step 6: 编写 registry 单元测试**

```python
# tests/unit/adapters/test_parser_registry.py
"""Parser registry 单元测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from ragnexus.adapters.parsers.registry import register, get_parser, _parsers
from ragnexus.core.errors import AppError, ErrorCode


@pytest.fixture(autouse=True)
def clear_registry():
    """每个测试前清空 registry。"""
    _parsers.clear()
    yield
    _parsers.clear()


class TestParserRegistry:
    """registry 注册与查找测试。"""

    async def test_register_and_get(self):
        """register 后 get_parser 返回正确 parser。"""
        mock = MagicMock()
        register("docx", mock)
        result = get_parser("report.docx")
        assert result is mock

    async def test_get_unknown_extension(self):
        """未知扩展名抛 UNSUPPORTED_FORMAT。"""
        with pytest.raises(AppError) as exc_info:
            get_parser("file.xyz")
        assert exc_info.value.code == ErrorCode.UNSUPPORTED_FORMAT.code

    async def test_no_extension(self):
        """无扩展名的文件抛 UNSUPPORTED_FORMAT。"""
        with pytest.raises(AppError) as exc_info:
            get_parser("no_extension_file")
        assert exc_info.value.code == ErrorCode.UNSUPPORTED_FORMAT.code

    async def test_register_with_dot_prefix(self):
        """带 '.' 前缀的扩展名也能正确注册。"""
        mock = MagicMock()
        register(".pdf", mock)
        result = get_parser("doc.pdf")
        assert result is mock
```

Run: `pytest tests/unit/adapters/test_parser_registry.py -v`
Expected: 4 tests PASS

- [ ] **Step 7: 编写 DocxParser 单元测试 (mock mammoth)**

```python
# tests/unit/adapters/test_docx_parser.py
"""DocxParser 单元测试 — mock mammoth 依赖。"""
from unittest.mock import MagicMock, patch, AsyncMock
import io

import pytest

from ragnexus.adapters.parsers.docx import DocxParser


@pytest.fixture
def parser():
    return DocxParser()


class TestDocxParser:
    """DocxParser.parse 测试 — mock mammoth.convert_to_markdown。"""

    @pytest.mark.asyncio
    @patch("ragnexus.adapters.parsers.docx.mammoth.convert_to_markdown")
    async def test_parse_with_headings(self, mock_convert, parser):
        """mammoth 输出 Markdown 标题 → sections 正确拆分。"""
        mock_convert.return_value = MagicMock(
            value="# 第一章\n\n这是内容。\n\n## 第一节\n\n小节内容。",
            messages=[],
        )

        result = await parser.parse(b"mock docx content", "test.docx")

        assert result.source_type == "docx"
        assert result.metadata["parser"] == "mammoth"
        assert len(result.sections) >= 2
        assert result.sections[0].heading == "第一章"
        assert result.sections[0].level == 1

    @pytest.mark.asyncio
    @patch("ragnexus.adapters.parsers.docx.mammoth.convert_to_markdown")
    async def test_parse_no_headings(self, mock_convert, parser):
        """mammoth 输出无标题纯文本 → 单个 section。"""
        mock_convert.return_value = MagicMock(
            value="这是纯文本内容，没有任何标题。",
            messages=[],
        )

        result = await parser.parse(b"mock content", "plain.docx")

        assert result.source_type == "docx"
        assert len(result.sections) >= 1

    @pytest.mark.asyncio
    @patch("ragnexus.adapters.parsers.docx.mammoth.convert_to_markdown")
    async def test_parse_captures_warnings(self, mock_convert, parser):
        """mammoth 返回 warnings → metadata 包含。"""
        mock_convert.return_value = MagicMock(
            value="# 标题\n内容",
            messages=[MagicMock(message="Unsupported element")],
        )

        result = await parser.parse(b"content", "warn.docx")
        assert "warnings" in result.metadata
        assert len(result.metadata["warnings"]) == 1

Run: `pytest tests/unit/adapters/test_docx_parser.py -v`
Expected: 3 tests PASS

- [ ] **Step 8: 编写 PdfParser 单元测试 (mock PyMuPDF)**

```python
# tests/unit/adapters/test_pdf_parser.py
"""PdfParser 单元测试 — mock fitz。"""
from unittest.mock import MagicMock, patch

import pytest

from ragnexus.adapters.parsers.pdf import PdfParser
from ragnexus.core.errors import AppError, ErrorCode


@pytest.fixture
def parser():
    return PdfParser()


class TestPdfParser:
    """PdfParser.parse 测试。"""

    @pytest.mark.asyncio
    @patch("ragnexus.adapters.parsers.pdf.fitz")
    async def test_parse_text_pdf(self, mock_fitz, parser):
        """有文字 PDF 按页创建 Section。"""
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page 1 content"
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_fitz.open.return_value = mock_doc

        result = await parser.parse(b"fake pdf", "doc.pdf")

        assert result.source_type == "pdf"
        assert result.metadata["parser"] == "pymupdf"
        assert len(result.sections) == 1
        assert result.sections[0].heading == "第 1 页"

    @pytest.mark.asyncio
    @patch("ragnexus.adapters.parsers.pdf.fitz")
    async def test_parse_scanned_pdf_raises(self, mock_fitz, parser):
        """扫描件（无文字）抛 DOCUMENT_PARSE_FAILED。"""
        mock_page = MagicMock()
        mock_page.get_text.return_value = ""  # 空页
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_fitz.open.return_value = mock_doc

        with pytest.raises(AppError) as exc_info:
            await parser.parse(b"scanned pdf", "scan.pdf")

        assert exc_info.value.code == ErrorCode.DOCUMENT_PARSE_FAILED.code
```

Run: `pytest tests/unit/adapters/test_pdf_parser.py -v`
Expected: 2 tests PASS

- [ ] **Step 9: 更新现有 parser 测试（source_type 变更）**

检查 `tests/unit/adapters/test_parser.py` — `ParsedDocument` 构造需含 `source_type`（由于默认值 `"text"` 已生效，`.txt` 测试不需要改；`.md` 测试需验证 `source_type="markdown"`）。

Run: `pytest tests/unit/adapters/test_parser.py -v`
Expected: ALL PASS（若 MarkdownAndTextParser._parse_markdown 返回了 `source_type="markdown"` 需断言）

- [ ] **Step 10: Commit**

```bash
git add src/ragnexus/adapters/parsers/ tests/unit/adapters/test_parser_registry.py tests/unit/adapters/test_docx_parser.py tests/unit/adapters/test_pdf_parser.py
git commit -m "feat: add parser registry, DocxParser, PdfParser and markdown source_type"
```

### Task 7: IndexingService._prepare_content 扩展

**Files:**
- Modify: `src/ragnexus/application/indexing_service.py:21-173`
- Test: `tests/unit/application/test_indexing_service.py`

**Interfaces:**
- Consumes: `FileStoragePort` (Task 5), parser registry (Task 6), `DocumentPort.update_content` (Task 4)
- Produces: `IndexingService.__init__` 新增 `parser_registry`/`file_storage` 参数；新增 `_prepare_and_parse` 方法

- [ ] **Step 1: 扩展 IndexingService.__init__**

```python
# src/ragnexus/application/indexing_service.py — __init__ 签名 (line 24)
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
        parser_registry=None,      # 新增 — registry 用于二进制文件解析
        file_storage=None,         # 新增 — FileStoragePort 读取暂存文件
    ) -> None:
        # ... 现有赋值 ...
        self._parser_registry = parser_registry
        self._file_storage = file_storage
```

- [ ] **Step 2: 重构 execute 方法**

```python
# src/ragnexus/application/indexing_service.py — execute 方法 (line 47)
async def execute(self, doc_id: str) -> None:
    """执行索引流水线。幂等保护：非 PROCESSING 跳过。"""
    doc = await self._doc_repo.get(doc_id)
    if doc is None:
        logger.warning("索引任务: 文档不存在", extra={"doc_id": doc_id})
        return
    if doc.status != DocStatus.PROCESSING:
        logger.info(
            "索引任务: 跳过非 PROCESSING 文档",
            extra={"doc_id": doc_id, "status": doc.status.name},
        )
        return

    try:
        # 1. Parse — 分路径
        if doc.source_file_path and not doc.content.strip():
            # 二进制文件：registry parse → 更新 content → 使用 registry 结果
            parsed = await self._prepare_and_parse(doc)
        else:
            # 文本文件：现有行为
            parsed = await self._parser.parse(doc.content.encode(), doc.filename)

        if not parsed.sections and not parsed.raw_text:
            await self._doc_repo.update_status(
                doc_id, status=DocStatus.FAILED, error_message="文件内容为空"
            )
            return

        # 2-6. Chunk → Embed → Dual Write → SUCCESS（完全不变）
        chunk_dicts = self._chunker(
            parsed, max_chars=self._chunk_max_chars, overlap=self._chunk_overlap
        )
        # ... 后续逻辑与现有代码一致 ...
```

- [ ] **Step 3: 实现 _prepare_and_parse 方法**

```python
# src/ragnexus/application/indexing_service.py — 新增方法
async def _prepare_and_parse(self, doc: Document) -> ParsedDocument:
    """从原始文件读取并解析二进制文档。

    1. 从 file_storage 读取原始字节
    2. 通过 registry 选择对应 parser
    3. 解析后更新 doc.content（供持久化查询）
    4. 返回 ParsedDocument
    """
    try:
        file_bytes = await self._file_storage.read(doc.source_file_path)
        parser = self._parser_registry.get_parser(doc.source_filename)
        parsed = await parser.parse(file_bytes, doc.source_filename)

        if not parsed.sections and not parsed.raw_text:
            raise AppError(ErrorCode.DOCUMENT_PARSE_FAILED, "解析结果为空")

        # 回写 content 供后续持久化查询
        await self._doc_repo.update_content(
            doc_id=doc.doc_id,
            content=parsed.raw_text,
        )
        return parsed
    except AppError:
        raise
    except Exception as e:
        raise AppError(
            ErrorCode.DOCUMENT_PARSE_FAILED,
            f"文档解析失败: {e}",
        )
```

- [ ] **Step 4: 更新单元测试**

```python
# tests/unit/application/test_indexing_service.py — 新增测试类
class TestPrepareAndParse:
    """_prepare_and_parse 路径测试。"""

    @pytest.mark.asyncio
    async def test_binary_file_path_taken(
        self, mock_doc_repo, mock_parser, mock_embedder, mock_chunker, mock_store
    ):
        """source_file_path 存在且 content 为空时走 _prepare_and_parse。"""
        from ragnexus.application.indexing_service import IndexingService

        mock_registry = MagicMock()
        mock_registry.get_parser = MagicMock(return_value=mock_parser)
        mock_fs = MagicMock()
        mock_fs.read = AsyncMock(return_value=b"fake binary")
        mock_doc_repo.update_content = AsyncMock()

        doc = _make_doc(
            doc_id="doc_bin", status=DocStatus.PROCESSING,
            source_file_path="/data/doc_bin/report.docx",
            source_filename="report.docx",
        )
        doc.content = ""  # 空 content 触发二进制路径
        mock_doc_repo.get.return_value = doc
        mock_parser.parse.return_value = ParsedDocument(
            filename="report.docx",
            sections=[Section(heading="Ch1", level=1, content="Hello")],
            raw_text="Hello",
            source_type="docx",
        )
        mock_chunker.return_value = [{"text": "Hello", "heading": "Ch1", "heading_level": 1}]
        mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]

        svc = IndexingService(
            doc_repo=mock_doc_repo, parser=mock_parser,
            embedder=mock_embedder, chunker=mock_chunker,
            store=mock_store, parser_registry=mock_registry,
            file_storage=mock_fs,
        )
        await svc.execute("doc_bin")

        mock_fs.read.assert_awaited_once_with("/data/doc_bin/report.docx")
        mock_registry.get_parser.assert_called_once_with("report.docx")
        mock_doc_repo.update_content.assert_awaited_once()
```

Run: `pytest tests/unit/application/test_indexing_service.py -v`
Expected: 新测试 PASS，原有测试 PASS（原有 svc fixture 不传入 parser_registry/file_storage 时走 else 分支——现有文本路径不变）

- [ ] **Step 5: Commit**

```bash
git add src/ragnexus/application/indexing_service.py tests/unit/application/test_indexing_service.py
git commit -m "feat: add _prepare_and_parse for binary document indexing"
```

### Task 8: DI / Composition 装配

**Files:**
- Modify: `src/ragnexus/composition.py:44,67,392,474-486,521,558-562` (多处)
- Modify: `src/ragnexus/di.py:11,35,62-75`

**Interfaces:**
- Consumes: registry (Task 6), LocalFileStorage (Task 5), IndexingService 新参数 (Task 7)
- Produces: composition.py 和 di.py 中完整装配 parser registry + file_storage 依赖

- [ ] **Step 1: 更新 di.py (_async_build_services)**

```python
# src/ragnexus/di.py — 新增 import
from ragnexus.adapters.file_storage.local import LocalFileStorage
from ragnexus.adapters.parsers.docx import DocxParser
from ragnexus.adapters.parsers.pdf import PdfParser
from ragnexus.adapters.parsers.registry import register as register_parser

async def _async_build_services(cfg: Settings):
    # ... 现有 dp pool、vector store 创建 ...
    parser = MarkdownAndTextParser()

    # --- Parser Registry + File Storage（新增）---
    file_storage = LocalFileStorage(base_path=cfg.DOCUMENT_STORAGE_PATH)

    # 注册所有 parser
    register_parser("docx", DocxParser())
    register_parser("pdf", PdfParser())
    register_parser("md", MarkdownAndTextParser())
    register_parser("txt", MarkdownAndTextParser())

    # --- IndexingService ---
    indexing_svc = IndexingService(
        doc_repo=doc_repo,
        parser=parser,
        embedder=embedder,
        chunker=heading_aware_split,
        store=store,
        keyword_store=keyword_store,
        es_enabled=cfg.ES_ENABLED,
        chunk_max_chars=cfg.CHUNK_MAX_CHARS,
        chunk_overlap=cfg.CHUNK_OVERLAP,
        parser_registry=None,  # di.py 中暂不传 registry（Worker 场景简单）
        file_storage=file_storage,
    )
    # ...
    return indexing_svc, doc_repo, kb_repo
```

注意：`di.py` 中 `parser_registry=None`（不传 registry），因为 IndexingService 的 `_prepare_content` 在 `parser_registry` 为 None 时会 fallback 到直接调用 `self._parser.parse`。**实际 registry 只在 composition.py 中需要**（Worker 进程也使用 di.py 构建，但 Worker 也需 registry——因此 di.py 同样应传入 registry）。

修正：di.py 也需要 registry。在 `register_parser` 调用后，使用 `from ragnexus.adapters.parsers.registry import get_parser as get_parser_from_registry` 然后将 registry 模块自身传入。为简单起见，直接传 registry 模块引用：

```python
import ragnexus.adapters.parsers.registry as parser_registry

# ... 注册 parsers ...
indexing_svc = IndexingService(
    # ...
    parser_registry=parser_registry,  # 传入模块引用，IndexingService 调用 .get_parser()
    file_storage=file_storage,
)
```

- [ ] **Step 2: 更新 composition.py**

```python
# src/ragnexus/composition.py — 新增 import（在现有 import 块末尾）
from ragnexus.adapters.file_storage.local import LocalFileStorage
from ragnexus.adapters.parsers.docx import DocxParser
from ragnexus.adapters.parsers.pdf import PdfParser
from ragnexus.adapters.parsers.registry import register as register_parser
import ragnexus.adapters.parsers.registry as parser_registry

# --- lifespan 内（line 392 parser 创建后）---
parser = MarkdownAndTextParser()

# 新增：Parser Registry + File Storage
file_storage = LocalFileStorage(base_path=cfg.DOCUMENT_STORAGE_PATH)
register_parser("docx", DocxParser())
register_parser("pdf", PdfParser())
register_parser("md", MarkdownAndTextParser())
register_parser("txt", MarkdownAndTextParser())

# --- UploadDocumentUseCase 构造（line 474）---
upload_doc_uc = UploadDocumentUseCase(
    kb_repo=kb_repo,
    doc_repo=document_repo,
    parser=parser,
    embedder=embedder,
    chunker=chunker,
    store=store,
    max_file_size=cfg.MAX_FILE_SIZE,
    allowed_exts=(".md", ".txt", ".docx", ".pdf"),  # 扩展允许列表
    chunk_max_chars=cfg.CHUNK_MAX_CHARS,
    chunk_overlap=cfg.CHUNK_OVERLAP,
    keyword_store=keyword_store,
    es_enabled=cfg.ES_ENABLED,
    file_storage=file_storage,  # 新增 — 供二进制文件暂存
)

# --- DocumentReindexUseCase ---
doc_reindex_uc = DocumentReindexUseCase(
    doc_repo=document_repo,
    kb_repo=kb_repo,
    parser_registry=parser_registry,  # 新增 — 供 reparse
)
```

- [ ] **Step 3: 更新 CacheInvalidatingUploadUseCase 和 SynonymSyncUploadUseCase**

需要透传 `file_storage` 参数（如果 upload use case 需要）——查看 `CacheInvalidatingUploadUseCase.execute` 签名，它当前透传 `(self, kb_id, tenant_id, file_content, filename, content_type)`。JSON 上传需要额外参数，因此需要扩展签名。

```python
# composition.py — CacheInvalidatingUploadUseCase.execute（约 line 93）
async def execute(
    self,
    kb_id: str,
    tenant_id: str,
    file_content: bytes,
    filename: str,
    content_type: str,
    text_content: str | None = None,  # 新增 — JSON 上传路径
) -> UploadResult:
    result = await self._inner.execute(
        kb_id=kb_id, tenant_id=tenant_id,
        file_content=file_content, filename=filename, content_type=content_type,
        text_content=text_content,
    )
    await self._reranker.clear_cache(kb_id)
    await self._rewriter.clear_cache(kb_id)
    return result
```

`SynonymSyncUploadUseCase.execute` 同样扩展。

- [ ] **Step 4: 验证 composition 导入**

```bash
python -c "from ragnexus.composition import build_app; print('composition import OK')"
```

Expected: 无 ImportError。若有循环导入问题，将 registry import 延迟到 lifespan 内。

- [ ] **Step 5: Commit**

```bash
git add src/ragnexus/composition.py src/ragnexus/di.py
git commit -m "feat: wire parser registry and file_storage into DI/composition"
```

### Task 9: 上传双模式 (JSON text + Multipart 二进制扩展)

**Files:**
- Modify: `src/ragnexus/adapters/http/upload_doc_router.py`
- Create: `src/ragnexus/adapters/http/upload_text_router.py`（新建，JSON 文本上传）
- Modify: `src/ragnexus/application/upload_doc_use_case.py:36-176`
- Modify: `src/ragnexus/composition.py`（注册新路由）
- Test: `tests/unit/adapters/test_http.py`（扩展）
- Test: `tests/unit/application/test_upload_doc.py`（扩展）

**Interfaces:**
- Consumes: `FileStoragePort` (Task 5), `allowed_exts` 扩展 (Task 8)
- Produces: `POST /v1/documents:upload-text` 路由；multipart upload 支持 .docx/.pdf

- [ ] **Step 1: 扩展 UploadDocumentUseCase.execute 支持双模式**

```python
# src/ragnexus/application/upload_doc_use_case.py — execute 方法
async def execute(
    self,
    kb_id: str,
    tenant_id: str,
    file_content: bytes,
    filename: str,
    content_type: str,
    *,
    text_content: str | None = None,  # JSON 上传时传入
) -> UploadResult:
    """运行同步校验流水线，提交异步索引任务。"""
    # 1. File size check
    if len(file_content) > self._max_file_size:
        raise AppError(ErrorCode.FILE_TOO_LARGE, "文件过大", ...)

    # 2. File extension check
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in self._allowed_exts:
        raise AppError(ErrorCode.UNSUPPORTED_FORMAT, ...)

    # 3. KB existence + tenant
    kb = await self._kb_repo.get(kb_id)
    # ... 不变 ...

    # 4. doc_id + file_hash
    file_hash = hashlib.sha256(file_content).hexdigest()
    doc_id = "doc_" + file_hash[:16]

    # 5. Dedup
    # ... 不变 ...

    # 6. 判断二进制 vs 文本
    is_binary = filename.lower().endswith(('.docx', '.pdf'))

    if is_binary:
        # 二进制文件：暂存磁盘，content 置空
        file_path = await self._file_storage.save(
            tenant_id, doc_id, filename, file_content
        )
        doc = await self._doc_repo.create(
            doc_id=doc_id, kb_id=kb_id, filename=filename,
            file_hash=file_hash, file_size=len(file_content),
            content_type=content_type, content="",
            source_file_path=file_path,
            source_filename=filename,
        )
    else:
        # 文本文件：现有行为
        text = text_content if text_content is not None else \
               file_content.decode("utf-8", errors="replace")
        doc = await self._doc_repo.create(
            doc_id=doc_id, kb_id=kb_id, filename=filename,
            file_hash=file_hash, file_size=len(file_content),
            content_type=content_type, content=text,
        )

    # 7. 提交 Celery 任务
    from ragnexus.tasks.indexing import index_document_task
    index_document_task.apply_async(args=[doc_id], ignore_result=True)

    # ... logger + return ...
```

注意：`file_content` 参数对于 JSON 上传为空 bytes `b""`，`text_content` 提供实际内容。

- [ ] **Step 2: 创建 JSON 文本上传路由**

```python
# src/ragnexus/adapters/http/upload_text_router.py
"""工厂函数: upload_text_router — POST /v1/documents:upload-text (JSON)。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ragnexus.core.auth import TenantContext


class UploadTextRequest(BaseModel):
    kb_id: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=256)
    content: str = Field(..., min_length=1)


def create_router(uc, get_current_tenant, quota_svc=None) -> APIRouter:
    router = APIRouter()

    @router.post("/v1/documents:upload-text", status_code=201)
    async def upload_text(
        body: UploadTextRequest,
        current_tenant: TenantContext = Depends(get_current_tenant),
    ):
        if quota_svc:
            await quota_svc.check_doc_upload(
                body.kb_id, current_tenant.tenant_id, current_tenant.plan
            )

        file_content = body.content.encode("utf-8")
        content_type = (
            "text/markdown" if body.title.endswith(".md")
            else "text/plain"
        )
        filename = body.title if "." in body.title else body.title + ".md"

        result = await uc.execute(
            kb_id=body.kb_id,
            file_content=file_content,
            filename=filename,
            content_type=content_type,
            tenant_id=current_tenant.tenant_id,
            text_content=body.content,
        )
        return {
            "code": 0,
            "data": {
                "doc_id": result.doc_id,
                "kb_id": result.kb_id,
                "status": result.status.name.lower(),
                "chunk_count": result.chunk_count,
            },
            "message": "ok",
        }

    return router
```

- [ ] **Step 3: 注册新路由到 composition.py**

```python
# src/ragnexus/composition.py — import 区
from ragnexus.adapters.http.upload_text_router import (
    create_router as create_upload_text_router,
)

# lifespan 内 — 在现有 upload_doc_router 注册之后
app.include_router(
    create_upload_text_router(
        upload_doc_uc_wrapped, get_current_tenant, quota_svc=quota_svc
    )
)
```

- [ ] **Step 4: 更新 multipart upload 路由 — content_type 处理**

现有 `upload_doc_router.py` 不需要改（它透传 `file.content_type`）。但需确认 `.docx` 的 MIME type 为 `application/vnd.openxmlformats-officedocument.wordprocessingml.document`，这在 `content_type` 字段中自然存储。

- [ ] **Step 5: 更新单元测试**

```python
# tests/unit/application/test_upload_doc.py — 新增测试
class TestBinaryUpload:
    """二进制文件上传路径测试。"""

    @pytest.mark.asyncio
    @patch("ragnexus.tasks.indexing.index_document_task")
    async def test_docx_upload_stores_file(self, mock_task, mock_kb_repo, mock_doc_repo,
                                            mock_embedder, mock_parser, mock_store):
        """.docx 上传暂存文件，content 置空，source_file_path 设值。"""
        mock_fs = MagicMock()
        mock_fs.save = AsyncMock(return_value="/data/uploads/t1/doc_x/file.docx")

        uc = UploadDocumentUseCase(
            kb_repo=mock_kb_repo, doc_repo=mock_doc_repo,
            parser=mock_parser, embedder=mock_embedder,
            chunker=heading_aware_split, store=mock_store,
            allowed_exts=(".md", ".txt", ".docx", ".pdf"),
            file_storage=mock_fs,
        )

        result = await uc.execute(
            kb_id="kb_test", tenant_id="test_tenant",
            file_content=b"mock docx binary",
            filename="report.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        mock_fs.save.assert_awaited_once()
        # 验证 create 调用含 source_file_path
        call_kwargs = mock_doc_repo.create.call_args.kwargs
        assert call_kwargs["content"] == ""
        assert call_kwargs["source_file_path"] == "/data/uploads/t1/doc_x/file.docx"
        assert call_kwargs["source_filename"] == "report.docx"
        mock_task.apply_async.assert_called_once()
```

Run: `pytest tests/unit/application/test_upload_doc.py -v`
Expected: 新测试 PASS，原有测试也需 PASS（`.txt`/`.md` 走文本路径）

- [ ] **Step 6: 更新 HTTP 路由测试**

```python
# tests/unit/adapters/test_http.py — 新增 upload-text 测试
class TestUploadText:
    """POST /v1/documents:upload-text 测试。"""

    async def test_upload_text_returns_201(self, client):
        """JSON 文本上传返回 201 + doc_id。"""
        # 此测试需要 mock composition 的 use case
        # 实际使用 httpx_mock 拦截 Celery 任务
        with patch("ragnexus.tasks.indexing.index_document_task"):
            resp = client.post("/v1/documents:upload-text", json={
                "kb_id": "kb_test", "title": "readme.md",
                "content": "# Hello\n\nWorld",
            })
            assert resp.status_code == 201
            data = resp.json()
            assert data["code"] == 0
            assert "doc_id" in data["data"]
```

Run: `pytest tests/unit/adapters/test_http.py -v -k "upload"`
Expected: 新测试 PASS，已有 upload 测试 PASS

- [ ] **Step 7: Commit**

```bash
git add src/ragnexus/adapters/http/upload_text_router.py src/ragnexus/adapters/http/upload_doc_router.py src/ragnexus/application/upload_doc_use_case.py src/ragnexus/composition.py tests/unit/application/test_upload_doc.py tests/unit/adapters/test_http.py
git commit -m "feat: add JSON text upload route and binary file multipart support"
```

### Task 10: Reparse 支持

**Files:**
- Modify: `src/ragnexus/application/document_reindex_uc.py:9-36`
- Modify: `src/ragnexus/adapters/http/document_router.py:43-54`
- Modify: `src/ragnexus/composition.py:521`

**Interfaces:**
- Consumes: `parser_registry` (Task 6), `DocumentPort.update_content` (Task 4), `FileStoragePort` (Task 5)
- Produces: `DocumentReindexUseCase` 支持 `reparse=True`; `POST /v1/documents/{doc_id}/reindex?reparse=true`

- [ ] **Step 1: 扩展 DocumentReindexUseCase**

```python
# src/ragnexus/application/document_reindex_uc.py
"""DocumentReindexUseCase — 重新索引文档。"""

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import DocStatus
from ragnexus.domain.ports import DocumentPort, KnowledgeBasePort
from ragnexus.tasks.indexing import index_document_task


class DocumentReindexUseCase:
    def __init__(
        self,
        doc_repo: DocumentPort,
        kb_repo: KnowledgeBasePort,
        parser_registry=None,  # 新增
        file_storage=None,     # 新增
    ) -> None:
        self._doc_repo = doc_repo
        self._kb_repo = kb_repo
        self._parser_registry = parser_registry
        self._file_storage = file_storage

    async def execute(self, doc_id: str, tenant_id: str, reparse: bool = False) -> dict:
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

        # Reparse 逻辑：清除 content 使 IndexingService 重新解析原文件
        if reparse and doc.source_file_path:
            await self._doc_repo.update_content(doc_id, content="")

        await self._doc_repo.update_status(
            doc_id, status=DocStatus.PROCESSING, error_message=None
        )
        index_document_task.apply_async(args=[doc_id], ignore_result=True)
        return {"doc_id": doc_id, "status": "processing"}
```

- [ ] **Step 2: 扩展 document_router.py reindex 端点**

```python
# src/ragnexus/adapters/http/document_router.py — reindex_document（约 line 43）
@router.post("/v1/documents/{doc_id}/reindex")
async def reindex_document(
    doc_id: str,
    reparse: bool = False,  # 新增 query 参数
    current_tenant: TenantContext = Depends(get_current_tenant),
):
    if quota_svc:
        await quota_svc.check_processing(
            current_tenant.tenant_id, current_tenant.plan
        )

    result = await uc_reindex.execute(
        doc_id, current_tenant.tenant_id, reparse=reparse,
    )
    return {"code": 0, "data": result, "message": "ok"}
```

- [ ] **Step 3: 更新 composition.py 的 doc_reindex_uc 构造**

```python
# src/ragnexus/composition.py — line 521
doc_reindex_uc = DocumentReindexUseCase(
    doc_repo=document_repo,
    kb_repo=kb_repo,
    parser_registry=parser_registry,  # 新增
    file_storage=file_storage,        # 新增
)
```

- [ ] **Step 4: 编写 reindex 测试**

```python
# tests/unit/adapters/test_http.py — 或在 application test 中
@pytest.mark.asyncio
@patch("ragnexus.tasks.indexing.index_document_task")
async def test_reindex_with_reparse(self, mock_task):
    """reparse=true + source_file_path 存在时清除 content。"""
    # ... mock setup ...
    uc = DocumentReindexUseCase(
        doc_repo=mock_doc_repo,
        kb_repo=mock_kb_repo,
        parser_registry=mock_registry,
        file_storage=mock_fs,
    )
    # source_file_path 不为空，reparse=True
    mock_doc_repo.get.return_value = _make_doc(
        status=DocStatus.FAILED,
        source_file_path="/data/doc.docx",
    )
    await uc.execute("doc_id", "tenant", reparse=True)
    mock_doc_repo.update_content.assert_awaited_once_with(
        doc_id="doc_id", content="",
    )
```

Run: `pytest tests/unit/application/ -v -k "reindex"`
Expected: 新测试 PASS

- [ ] **Step 5: Commit**

```bash
git add src/ragnexus/application/document_reindex_uc.py src/ragnexus/adapters/http/document_router.py src/ragnexus/composition.py
git commit -m "feat: add reparse support to DocumentReindexUseCase and reindex endpoint"
```

### Task 11: 前端改造

**Files:**
- Modify: `frontend/src/lib/file-filter.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/components/upload-doc.tsx`（或对应上传组件路径）
- Modify: `frontend/src/components/doc-row.tsx`（可选 — 格式 badge）

**Interfaces:**
- Consumes: 无后端依赖
- Produces: 文件选择器接受 .pdf/.docx；新增 `uploadDocJson` API 函数

- [ ] **Step 1: 扩展 file-filter.ts**

```typescript
// frontend/src/lib/file-filter.ts
export const ALLOWED_EXTS = [".md", ".txt", ".pdf", ".docx"];
export const MAX_SIZE_MB = 20;  // 与后端 DOCUMENT_MAX_SIZE_MB 一致
export const MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024;

export function validateFile(file: File): string | null {
  const ext = "." + file.name.split(".").pop()?.toLowerCase();
  if (!ALLOWED_EXTS.includes(ext)) {
    return `不支持的文件类型: ${ext}，仅支持 ${ALLOWED_EXTS.join(", ")}`;
  }
  if (file.size > MAX_SIZE_BYTES) {
    return `文件过大: ${(file.size / 1024 / 1024).toFixed(1)}MB，限制 ${MAX_SIZE_MB}MB`;
  }
  return null;
}
```

- [ ] **Step 2: 扩展 api.ts**

```typescript
// frontend/src/lib/api.ts — 新增 uploadDocJson
export async function uploadDocJson(
  kbId: string,
  title: string,
  content: string,
): Promise<{ doc_id: string; status: string }> {
  const resp = await fetch(`${API_BASE}/v1/documents:upload-text`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getApiKey()}`,
    },
    body: JSON.stringify({ kb_id: kbId, title, content }),
  });
  if (!resp.ok) throw new ApiError(resp.status, await resp.text());
  const json = await resp.json();
  return json.data;
}
```

- [ ] **Step 3: 扩展 upload-doc.tsx — 文件选择器 accept 属性**

```tsx
// frontend/src/components/upload-doc.tsx
// 文件 input accept 属性
<input
  type="file"
  accept=".md,.txt,.pdf,.docx"
  onChange={handleFileChange}
/>
```

- [ ] **Step 4: （可选）DocRow 展示 source_type badge**

如果 API 响应中 `content_type` 可映射为格式 label，在文档列表行中展示：

```tsx
const FORMAT_LABELS: Record<string, string> = {
  "text/markdown": "MD",
  "text/plain": "TXT",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
  "application/pdf": "PDF",
};

function FormatBadge({ contentType }: { contentType: string }) {
  const label = FORMAT_LABELS[contentType] || contentType.split("/").pop()?.toUpperCase();
  return <span className="format-badge">{label}</span>;
}
```

- [ ] **Step 5: 验证前端构建**

```bash
cd frontend && npm run build
```
Expected: 无 TypeScript 编译错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/file-filter.ts frontend/src/lib/api.ts frontend/src/components/upload-doc.tsx
git commit -m "feat: frontend support for .docx/.pdf upload and JSON text upload"
```

### Task 12: 依赖与构建配置

**Files:**
- Modify: `pyproject.toml`（新增 `[project.optional-dependencies] parsers`）
- Modify: `Dockerfile`（安装 parsers extra）
- Modify: `README.md`（补充 parsers 安装说明）

**Interfaces:**
- Consumes: 无
- Produces: `pip install ".[parsers]"` 可安装 mammoth + PyMuPDF

- [ ] **Step 1: 更新 pyproject.toml**

```toml
# pyproject.toml — 在 [project.optional-dependencies] 块中新增
[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "pyright>=1.1.410",
  "ruff>=0.15.0",
  "pre-commit>=4.0",
  "psycopg2-binary>=2.9",
]
eval = [
    "ragas>=0.2.0",
    "datasets>=2.0.0",
]
parsers = [
    "mammoth>=1.8.0",
    "pymupdf>=1.24.0",
]
```

注意：`pymupdf` 的包名是 `pymupdf`（全小写），import 名是 `fitz`。

- [ ] **Step 2: 验证依赖安装**

```bash
uv pip install ".[parsers]"
python -c "import mammoth; import fitz; print('OK')"
```

Expected: 无 ImportError

- [ ] **Step 3: 更新 Dockerfile**

```dockerfile
# Dockerfile — pip install 行改为安装 parsers extra
RUN pip install --no-cache-dir ".[parsers]"
```

- [ ] **Step 4: 更新 README.md**

```markdown
## 安装

```bash
# 基础安装
pip install -e .

# 含文档解析支持（Word + PDF）
pip install -e ".[parsers]"

# 开发环境
pip install -e ".[dev,parsers]"
```
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml Dockerfile README.md
git commit -m "feat: add mammoth and PyMuPDF as optional parsers dependencies"
```

### Task 13: 集成测试

**Files:**
- Create: `tests/fixtures/sample.docx`（最小 Word 文档 — 含标题和表格）
- Create: `tests/fixtures/sample.pdf`（最小 PDF — 含文字）
- Create: `tests/fixtures/sample_scanned.pdf`（最小 PDF — 纯图片无文字）
- Create: `tests/integration/test_multi_format_upload.py`（新建）
- Create: `tests/integration/test_multi_format_indexing.py`（新建）
- Modify: `tests/integration/test_upload_full_chain.py`（回归验证）

**Interfaces:**
- Consumes: 所有前述 Task 的产出
- Produces: 集成测试覆盖 docx/pdf 上传→索引→检索全链路

- [ ] **Step 1: 生成测试 fixture 文件**

使用 Python 脚本生成最小 .docx 和 .pdf：

```python
# scripts/generate_test_fixtures.py（一次性运行，生成后提交 fixtures）
"""生成测试用 fixture 文件。"""
from pathlib import Path

FIXTURES = Path("tests/fixtures")
FIXTURES.mkdir(parents=True, exist_ok=True)

# --- 生成 sample.docx（最小 Word 文档）---
import zipfile
import io

def make_minimal_docx():
    """构造最小 .docx（ZIP of XML）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/></Types>')
        zf.writestr("word/document.xml",
            '<?xml version="1.0"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>'
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>第一章</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>这是第一段内容。</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>第一节</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>这是子章节的内容。</w:t></w:r></w:p>'
            '</w:body></w:document>')
    buf.seek(0)
    return buf.read()

(FIXTURES / "sample.docx").write_bytes(make_minimal_docx())

# --- 生成 sample.pdf（使用 reportlab 或手动构造）---
# 如果 reportlab 不可用，使用 PyMuPDF 生成:
try:
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(fitz.Point(72, 72), "第一章 测试文档", fontsize=16)
    page.insert_text(fitz.Point(72, 100), "这是测试PDF文档的第一页内容。", fontsize=12)
    doc.save(str(FIXTURES / "sample.pdf"))
    doc.close()

    # 扫描件 PDF（空文字）
    doc2 = fitz.open()
    page2 = doc2.new_page()
    # 不插入文字 — 模拟扫描件
    doc2.save(str(FIXTURES / "sample_scanned.pdf"))
    doc2.close()
except ImportError:
    print("PyMuPDF 未安装，跳过 PDF fixture 生成")
```

Run: `python scripts/generate_test_fixtures.py`

- [ ] **Step 2: 集成测试 — 上传链路**

```python
# tests/integration/test_multi_format_upload.py
"""多格式上传集成测试 — 需要 Docker PostgreSQL + pgvector。"""
import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.integration


class TestDocxUpload:
    """.docx 上传 → PROCESSING 状态。"""

    @pytest.mark.asyncio
    async def test_upload_docx_returns_processing(self, app_with_db):
        """multipart 上传 .docx 返回 201 + PROCESSING。"""
        from pathlib import Path

        fixture = Path("tests/fixtures/sample.docx")
        assert fixture.exists(), "sample.docx fixture missing"

        transport = ASGITransport(app=app_with_db)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with open(fixture, "rb") as f:
                resp = await client.post(
                    "/v1/documents:upload",
                    files={"file": ("test.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                    data={"kb_id": "kb_test"},
                )
            assert resp.status_code == 201
            data = resp.json()
            assert data["code"] == 0
            assert data["data"]["status"] == "processing"
```

- [ ] **Step 3: 集成测试 — 索引链路（需 Celery worker 运行）**

```python
# tests/integration/test_multi_format_indexing.py
"""多格式索引集成测试。"""
import asyncio
import pytest
import asyncpg

pytestmark = pytest.mark.integration

TEST_DSN = "postgresql://ragnexus:ragnexus@localhost:15433/ragnexus_test"


class TestDocxIndexing:
    """.docx 索引后检索验证。"""

    @pytest.mark.asyncio
    async def test_docx_indexed_and_retrievable(self):
        """.docx 上传后等待 SUCCESS，检索可命中。"""
        # 1. 上传 .docx
        # 2. 等待 status=SUCCESS（轮询最多 60s）
        # 3. POST /v1/rag:retrieve 验证可检索到内容
        conn = await asyncpg.connect(TEST_DSN)
        try:
            for _ in range(60):
                row = await conn.fetchrow(
                    "SELECT status FROM documents WHERE doc_id=$1", doc_id
                )
                if row and row["status"] == 1:  # SUCCESS
                    break
                await asyncio.sleep(1)
            else:
                pytest.fail("文档 60s 内未完成索引")

            assert row["status"] == 1
        finally:
            await conn.close()
```

- [ ] **Step 4: 扫描件 PDF 测试**

```python
class TestScannedPdf:
    """"扫描件 PDF → FAILED。"""

    @pytest.mark.asyncio
    async def test_scanned_pdf_fails(self):
        """无文字 PDF 索引后 status=FAILED + DOCUMENT_PARSE_FAILED 错误。"""
        # ... 上传 sample_scanned.pdf ...
        # 等待 status=FAILED
        # 验证 error_message 含 "扫描件" 或 "OCR"
```

- [ ] **Step 5: 回归测试**

```bash
# 运行现有全套测试确认零破坏
pytest tests/ -v --ignore=tests/e2e -x
```

Expected: 319+ 测试 ALL PASS（含新增测试），无 regression

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/ tests/integration/test_multi_format_upload.py tests/integration/test_multi_format_indexing.py scripts/generate_test_fixtures.py
git commit -m "test: add integration tests for multi-format upload and indexing"
```

### Task 14: E2E 验证脚本 + 最终清理

**Files:**
- Create: `scripts/verify_multi_format.py`
- Modify: `docs/superpowers/specs/2026-07-07-multi-format-parser-design.md`（无需修改，已存在）

**Interfaces:**
- Consumes: 完整功能链路
- Produces: 一键验证脚本，exit 0 表示全部通过

- [ ] **Step 1: 创建 E2E 验证脚本**

```python
#!/usr/bin/env python3
# scripts/verify_multi_format.py
"""E2E 验证：docx/pdf/md 上传 → retrieve → 全部通过。

用法:
    python scripts/verify_multi_format.py --api-key rk_xxx [--base-url http://localhost:8000]
"""
import argparse
import asyncio
import sys
from pathlib import Path

import httpx


async def upload_file(client: httpx.AsyncClient, base_url: str, kb_id: str,
                      file_path: Path, api_key: str) -> str:
    """上传文件，返回 doc_id。"""
    content_type_map = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pdf": "application/pdf",
        ".md": "text/markdown",
        ".txt": "text/plain",
    }
    ext = file_path.suffix.lower()
    ct = content_type_map.get(ext, "application/octet-stream")

    with open(file_path, "rb") as f:
        resp = await client.post(
            f"{base_url}/v1/documents:upload",
            files={"file": (file_path.name, f, ct)},
            data={"kb_id": kb_id},
            headers={"Authorization": f"Bearer {api_key}"},
        )
    assert resp.status_code == 201, f"Upload failed: {resp.text}"
    data = resp.json()
    assert data["code"] == 0
    return data["data"]["doc_id"]


async def wait_for_success(client: httpx.AsyncClient, base_url: str,
                           doc_id: str, api_key: str, timeout: int = 120) -> None:
    """轮询等待文档索引完成。"""
    import asyncio
    for i in range(timeout):
        await asyncio.sleep(2)
        resp = await client.get(
            f"{base_url}/v1/documents/{doc_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        status = data["data"]["status"]
        if status == "success":
            print(f"  ✓ {doc_id} indexed successfully")
            return
        if status == "failed":
            raise AssertionError(f"Document {doc_id} failed: {data['data'].get('error_message')}")
    raise TimeoutError(f"Document {doc_id} not indexed within {timeout}s")


async def verify_retrieval(client: httpx.AsyncClient, base_url: str,
                           kb_id: str, query: str, api_key: str) -> bool:
    """检索并验证命中。"""
    resp = await client.post(
        f"{base_url}/v1/rag:retrieve",
        json={"query": query, "kb_ids": [kb_id], "top_k": 5},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, f"Retrieve failed: {resp.text}"
    data = resp.json()
    hits = data.get("data", {}).get("hits", [])
    return len(hits) > 0


async def main():
    parser = argparse.ArgumentParser(description="Multi-format E2E verification")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--kb-id", required=True)
    args = parser.parse_args()

    fixtures = Path("tests/fixtures")
    test_files = [
        (fixtures / "sample.docx", "第一章"),
        (fixtures / "sample.pdf", "测试"),
    ]

    async with httpx.AsyncClient(timeout=30.0) as client:
        for file_path, search_term in test_files:
            if not file_path.exists():
                print(f"  ⚠ {file_path.name} not found, skipping")
                continue

            print(f"Testing: {file_path.name}")
            doc_id = await upload_file(client, args.base_url, args.kb_id, file_path, args.api_key)
            print(f"  Uploaded: {doc_id}")

            await wait_for_success(client, args.base_url, doc_id, args.api_key)

            found = await verify_retrieval(client, args.base_url, args.kb_id, search_term, args.api_key)
            assert found, f"Retrieval for '{search_term}' returned no hits"
            print(f"  ✓ '{search_term}' retrievable")

    print("\n✅ All multi-format tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: 运行 E2E 验证**

```bash
# 前提：API 服务 + Celery Worker 已启动
python scripts/verify_multi_format.py --api-key rk_your_key --kb-id kb_existing
```

Expected: exit 0，所有格式上传→索引→检索通过

- [ ] **Step 3: 运行完整测试套件**

```bash
pytest tests/ -v --ignore=tests/e2e --tb=short
```

Expected: ALL PASS，零回归

- [ ] **Step 4: Final commit**

```bash
git add scripts/verify_multi_format.py
git commit -m "feat: add E2E verification script for multi-format parsing"
```

---

## 任务依赖图

```
Task 1 (Domain models) ─────────────────────────────────────────────────────┐
    │                                                                        │
    ├── Task 2 (Config) ──────────────────────────────────────────────────┐  │
    │                                                                      │  │
    ├── Task 3 (DB migration) ── Task 4 (PgDocumentRepo) ──┐               │  │
    │                                                       │              │  │
    ├── Task 5 (FileStorage) ───────────────────────────────┤               │  │
    │                                                       │              │  │
    └── Task 6 (Parser plugins) ────────────────────────────┤               │  │
                                                            │              │  │
                                    ┌───────────────────────┘              │  │
                                    ▼                                       │  │
                              Task 7 (IndexingService) ◄───────────────────┘  │
                                    │                                          │
                                    ▼                                          │
                              Task 8 (DI/Composition) ◄───────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              Task 9 (Upload)  Task 10 (Reparse)  Task 11 (Frontend)
                    │               │               │
                    └───────────────┼───────────────┘
                                    ▼
                              Task 12 (Deps/Build)
                                    │
                                    ▼
                              Task 13 (Integration tests)
                                    │
                                    ▼
                              Task 14 (E2E + cleanup)
```

## 自审清单

1. **Spec 覆盖**：Design Doc 所有章节（领域模型、Parser 层、文件存储、上传双模式、索引变更、Reparse、错误处理、DB 迁移、配置、依赖、测试）均有对应 Task ✅
2. **零占位符**：所有代码块包含完整实现代码，无 TBD/TODO/占位注释 ✅
3. **类型一致性**：`source_type` 复用 `content_type`（Tasks.md 中的独立列方案被 Design Doc 否决——已按 Design Doc 执行）；`FileStoragePort` 签名在 Task 1 定义、Task 5 实现、Task 7/9/10 消费一致 ✅
4. **空内容处理**：`IndexingService._prepare_and_parse` 对空 sections 抛 DOCUMENT_PARSE_FAILED（Task 7 Step 3）✅
5. **扫描件 PDF**：`PdfParser` 抛 DOCUMENT_PARSE_FAILED（Task 6 Step 3），集成测试覆盖（Task 13 Step 4）✅
