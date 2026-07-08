---
comet_change: multi-format-parser
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-08-multi-format-parser
status: final
---

# 多格式文档解析 — 技术设计

## 1. 概述

在 RAGNexus 现有文档处理流水线之前增加插件化解析层，支持 `.docx`（Word）和 `.pdf` 二进制格式的直接上传和自动解析。Parser 输出统一的 `ParsedDocument`（sections 结构），无缝接入现有 `heading_aware_split` → embed → ES+pgvector 双写流水线。

### 1.1 约束

- **零破坏**：`.md`/`.txt` 上传行为完全不变，JSON 文本上传新增独立路由
- **不改切块层**：`heading_aware_split` 签名、逻辑、消费方式不变
- **不改检索层**：`RetrieveUseCase`、embedding、向量存储、关键词检索均不感知
- **不改租户/配额系统**：`QuotaService`、`RateLimitService`、`TenantContext` 不新增字段

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────┐
│                   HTTP Layer (adapters/http)              │
│  POST /v1/documents:upload       (multipart, 现有)        │
│  POST /v1/documents:upload-text  (JSON, 新增)            │
│  POST /v1/documents/{id}/reindex (扩展 reparse 参数)      │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│              Application Layer                            │
│  UploadDocumentUseCase  ─── 同步校验 + 异步触发           │
│  IndexingService        ─── 新增 _prepare_content 步骤    │
│  DocumentReindexUseCase ─── 扩展 reparse 支持             │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│              Domain Layer (ports + models)                │
│  ParserPort      (现有, 不变)                             │
│  FileStoragePort (新增)                                   │
│  ParsedDocument  (扩展 source_type + metadata)            │
│  Document        (扩展 source_file_path + source_filename)│
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│              Adapter Layer                                │
│  parsers/registry.py  (新增 — 按扩展名选择 parser)         │
│  parsers/docx.py      (新增 — mammoth Word 解析)          │
│  parsers/pdf.py       (新增 — PyMuPDF PDF 解析)          │
│  parsers/md_and_txt.py(微调 — 增加 source_type)          │
│  file_storage/local.py(新增 — 本地文件系统存储)           │
│  document/pg.py       (扩展 — 支持新字段)                 │
└─────────────────────────────────────────────────────────┘
```

## 3. 领域模型变更

### 3.1 ParsedDocument 扩展

```python
@dataclass
class ParsedDocument:
    filename: str
    sections: list[Section]      # 不变
    raw_text: str                # 不变
    source_type: str = "text"    # 新增: text | markdown | docx | pdf
    metadata: dict = field(default_factory=dict)
    # metadata 内容:
    #   docx: {"parser": "mammoth", "warnings": [...]}
    #   pdf:  {"parser": "pymupdf", "page_count": N}
```

### 3.2 Document 扩展

```python
@dataclass
class Document:
    # ... 现有 12 字段不变 ...
    source_file_path: str | None = None    # 新增 — 原文件磁盘路径
    source_filename: str | None = None     # 新增 — 原始文件名
    # source_type 由 content_type 字段承担（content_type 原用于 MIME type，
    # 现同时承载格式来源语义: "text/markdown" → markdown, 
    # "application/vnd.openxmlformats-officedocument.wordprocessingml.document" → docx）
```

> **设计决策**：`source_type` 复用 `content_type` 字段而非新增列。理由：(1) 减少 migration 列数；(2) `content_type` 在上传时已有 MIME type，自然对应格式。如需在 API 响应中暴露为 `source_type`，在 schema 层做映射。

### 3.3 FileStoragePort

```python
class FileStoragePort(Protocol):
    async def save(self, tenant_id: str, doc_id: str, 
                   filename: str, content: bytes) -> str:
        """保存文件 → 返回存储路径"""
        ...

    async def read(self, path: str) -> bytes:
        """读取文件内容"""
        ...

    async def delete(self, path: str) -> None:
        """删除文件"""
        ...
```

## 4. Parser 插件层设计

### 4.1 Registry

```python
# adapters/parsers/registry.py

_parsers: dict[str, ParserPort] = {}

def register(ext: str, parser: ParserPort) -> None:
    _parsers[ext.lstrip(".").lower()] = parser

def get_parser(filename: str) -> ParserPort:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    parser = _parsers.get(ext)
    if parser is None:
        raise AppError(ErrorCode.UNSUPPORTED_FORMAT, ...)
    return parser
```

注册顺序（`composition.py` lifespan 中初始化）：

```python
from ragnexus.adapters.parsers.registry import register
from ragnexus.adapters.parsers.docx import DocxParser
from ragnexus.adapters.parsers.pdf import PdfParser
from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser

register("docx", DocxParser())
register("pdf", PdfParser())
register("md", MarkdownAndTextParser())
register("txt", MarkdownAndTextParser())
```

### 4.2 DocxParser

使用 mammoth 的 `convert_to_markdown` 公开 API，将 Word 转为 Markdown 后再由 `MarkdownAndTextParser._parse_markdown` 拆分为 sections：

```python
class DocxParser:
    async def parse(self, content: bytes, filename: str) -> ParsedDocument:
        import io, mammoth
        from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser
        
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

**标题映射**：mammoth 将 Word "标题 1/2" 样式自动转为 Markdown `#`/`##`，`_parse_markdown` 按 `#` 拆分 Section。

### 4.3 PdfParser

```python
class PdfParser:
    async def parse(self, content: bytes, filename: str) -> ParsedDocument:
        doc = fitz.open(stream=content, filetype="pdf")
        sections = []
        raw_parts = []
        
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            if text:
                sections.append(Section(
                    heading=f"第 {i + 1} 页",
                    level=2,
                    content=text,
                ))
                raw_parts.append(text)
        
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

## 5. 上传流水线变更

### 5.1 JSON 文本上传（新增路由）

```
POST /v1/documents:upload-text
Content-Type: application/json

{
    "kb_id": "kb_xxx",
    "title": "文档标题",
    "content": "## 章节一\n\n内容..."
}

→ 201 { "code": 0, "data": { "doc_id": "...", "status": "processing" } }
```

行为：与现有 multipart 上传 `.md`/`.txt` 完全一致（UTF-8 decode → content 直存 → Celery 任务）。

### 5.2 Multipart 上传扩展

现有 `POST /v1/documents:upload` 增加格式检测：

```
file.filename 以 .docx/.pdf 结尾
  → FileStorage.save() → Document(content='', source_file_path=path, content_type=mime)
  → Celery index_document_task

file.filename 以 .md/.txt 结尾
  → 现有行为不变（UTF-8 decode → content 直存）
```

### 5.3 UploadDocumentUseCase 扩展

```python
class UploadDocumentUseCase:
    def __init__(self, ..., file_storage: FileStoragePort | None = None):
        self._file_storage = file_storage

    async def execute(
        self, kb_id, tenant_id, file_content, filename, content_type,
        *, text_content: str | None = None,  # JSON 上传时传入
    ) -> UploadResult:
        # 1. 文件大小检查
        # 2. 扩展名检查 (allowed_exts: .md, .txt, .docx, .pdf)
        # 3. KB 存在+归属
        # 4. doc_id = doc_ + sha256[:16]
        # 5. 去重
        
        is_binary = filename.lower().endswith(('.docx', '.pdf'))
        
        if is_binary:
            # 二进制文件：暂存磁盘
            file_path = await self._file_storage.save(
                tenant_id, doc_id, filename, file_content
            )
            doc = await self._doc_repo.create(
                ...,
                content="",                     # 延迟解析
                source_file_path=file_path,
                source_filename=filename,
                content_type=content_type,       # MIME type → 同时承载 source_type
            )
        else:
            # 文本文件：现有行为
            text = text_content or file_content.decode("utf-8", errors="replace")
            doc = await self._doc_repo.create(
                ...,
                content=text,
                content_type=content_type,
            )
        
        # 提交 Celery 任务
        index_document_task.apply_async(args=[doc_id])
        return UploadResult(...)
```

## 6. 索引流水线变更

### 6.1 IndexingService._prepare_content

```python
class IndexingService:
    def __init__(self, ..., parser_registry=None, file_storage=None):
        self._parser_registry = parser_registry  # 新增
        self._file_storage = file_storage        # 新增

    async def execute(self, doc_id: str) -> None:
        doc = await self._doc_repo.get(doc_id)
        # ... 幂等检查 ...
        
        # 【新增步骤】二进制文件的内容准备
        if doc.source_file_path and not doc.content.strip():
            await self._prepare_content(doc)
            doc = await self._doc_repo.get(doc_id)  # 重新读取
        
        # 【现有流程，完全不变】
        parsed = await self._parser.parse(doc.content.encode(), doc.filename)
        # ... chunk → embed → 双写 ...

    async def _prepare_content(self, doc: Document) -> None:
        """从原始文件读取并解析，将结果写入 doc.content。"""
        try:
            file_bytes = await self._file_storage.read(doc.source_file_path)
            parser = self._parser_registry.get_parser(doc.source_filename)
            parsed = await parser.parse(file_bytes, doc.source_filename)
            
            if not parsed.sections and not parsed.raw_text:
                raise AppError(ErrorCode.DOCUMENT_PARSE_FAILED, "解析结果为空")
            
            # 更新 doc.content 为解析后的 raw_text（供后续 parser 消费）
            await self._doc_repo.update_content(
                doc_id=doc.doc_id,
                content=parsed.raw_text,
                # content_type 已经有正确的 MIME type
            )
        except AppError:
            raise
        except Exception as e:
            raise AppError(
                ErrorCode.DOCUMENT_PARSE_FAILED,
                f"文档解析失败: {e}",
            )
```

### 6.2 最终方案：分路径处理

二进制文件由 registry parser 解析后**直接**产出 `ParsedDocument`，不经过 `MarkdownAndTextParser` 的二次 parse。文本文件走现有路径不变。

```python
async def execute(self, doc_id: str) -> None:
    doc = await self._doc_repo.get(doc_id)
    # ... 幂等检查 ...

    # 1. Parse — 分路径
    if doc.source_file_path and not doc.content.strip():
        # 二进制文件：registry parse → 更新 DB content（持久化）→ 直接使用结果
        parsed = await self._prepare_and_parse(doc)
    else:
        # 文本文件：现有行为（MarkdownAndTextParser）
        parsed = await self._parser.parse(doc.content.encode(), doc.filename)

    if not parsed.sections and not parsed.raw_text:
        # ... FAILED ...
        return

    # 2-5. Chunk → Embed → Dual Write（完全不变）
    ...

async def _prepare_and_parse(self, doc: Document) -> ParsedDocument:
    """从原始文件解析并持久化，返回 ParsedDocument。"""
    file_bytes = await self._file_storage.read(doc.source_file_path)
    parser = self._parser_registry.get_parser(doc.source_filename)
    parsed = await parser.parse(file_bytes, doc.source_filename)
    # 持久化 raw_text 到 DB（供 reindex 和调试使用）
    await self._doc_repo.update_content(doc.doc_id, content=parsed.raw_text)
    return parsed
```

## 7. Reparse 支持

`POST /v1/documents/{doc_id}/reindex?reparse=true`

- `reparse=true` + `source_file_path` 存在：清除 content → 重新走 `_prepare_content` → 重新 index
- `reparse=true` + `source_file_path` 为 null：忽略参数，正常 reindex
- `reindex`（不带 reparse）：现有行为（只重新切块，不重新解析）

## 8. 错误处理

| 场景 | 错误码 | HTTP | 行为 |
|------|--------|------|------|
| 不支持扩展名 (.zip 等) | UNSUPPORTED_FORMAT (10400) | 415 | upload 阶段拒绝 |
| 文件超限 | FILE_TOO_LARGE (10401) | 413 | upload 阶段拒绝 |
| 解析抛异常 | DOCUMENT_PARSE_FAILED (20023) | 422 | 文档置 FAILED，error_message 含原因 |
| PDF 无文字 | DOCUMENT_PARSE_FAILED (20023) | - | FAILED，"疑似扫描件，本期不支持 OCR" |
| 解析成功但切块失败 | 现有错误码 | - | 沿用现有索引失败逻辑 |
| 上传时 Celery 未启动 | - | - | 文档停在 PROCESSING，Celery Beat 超时监控 |

**新增错误码**：
```python
DOCUMENT_PARSE_FAILED = (20023, 422, "文档解析失败")
```

## 9. 数据库迁移

```sql
ALTER TABLE documents ADD COLUMN source_file_path TEXT;
ALTER TABLE documents ADD COLUMN source_filename TEXT;
-- source_type 复用 content_type 字段，不新增列
```

> **注意**：`content_type` 字段已存在（`schema.sql:19`），上传时填充 MIME type。`.docx` 的 MIME type 为 `application/vnd.openxmlformats-officedocument.wordprocessingml.document`，可反向映射为 `docx`。API 响应中按需做映射。

## 10. 配置

```python
# config.py 新增
DOCUMENT_STORAGE_PATH: str = Field(default="./data/uploads")
DOCUMENT_MAX_SIZE_MB: int = Field(default=20)

# 移除旧的 max_file_size (10MB bytes)，改为从 DOCUMENT_MAX_SIZE_MB 计算
```

## 11. 依赖

```toml
# pyproject.toml
[project.optional-dependencies]
parsers = ["mammoth>=1.8.0", "pymupdf>=1.24.0"]
```

## 12. 测试策略

### 单元测试

| 测试 | 覆盖 |
|------|------|
| `test_docx_parser.py` | DocxParser 解析 sample.docx → sections 正确（标题层级、表格内容） |
| `test_pdf_parser.py` | PdfParser 解析 sample.pdf → sections 含 `第 N 页`，扫描件→异常 |
| `test_parser_registry.py` | 按扩展名正确选择 parser，未知格式→UNSUPPORTED_FORMAT |
| `test_upload_usecase.py` | JSON 模式、二进制暂存模式、文本直存模式 |
| `test_file_storage.py` | save/read/delete 正确性 |

### 集成测试

| 测试 | 覆盖 |
|------|------|
| `test_upload_flow.py` | multipart .docx → PROCESSING → SUCCESS；扫描件 PDF → FAILED |
| `test_regression.py` | JSON .md 上传 → 行为与改造前一致 |

### E2E 验证脚本

`scripts/verify_multi_format.py`：依次上传 docx/pdf/md → 等待 SUCCESS → retrieve 验证 → exit 0

### 回归测试

运行现有 319 个测试确认零破坏。

## 13. 未覆盖的边界

- **大 PDF（>100MB）**：`DOCUMENT_MAX_SIZE_MB` 在 upload 阶段拦截；PyMuPDF 按页流式读取，内存可控
- **加密 PDF**：PyMuPDF 会抛异常 → catch → DOCUMENT_PARSE_FAILED
- **并发上传同一文件**：去重检查（SHA256）在 upload 阶段拦截
- **磁盘满**：`FileStoragePort.save()` 抛 OSError → 文档置 FAILED
