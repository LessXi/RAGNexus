# Task 1: 领域模型扩展

## Plan Section

来自 `docs/superpowers/plans/2026-07-07-multi-format-parser.md` Task 1。

### 目标

扩展三个领域模型文件，为多格式文档解析提供数据基础。

### 要修改的文件

1. `src/ragnexus/domain/models.py` — ParsedDocument (line 34-38), Document (line 72-87)
2. `src/ragnexus/domain/ports.py` — 在 ParserPort 之后新增 FileStoragePort
3. `src/ragnexus/core/errors.py` — 在 FEEDBACK_INVALID_SCORE 后新增 DOCUMENT_PARSE_FAILED

### 变更详述

#### 1.1 扩展 ParsedDocument (models.py:34-38)

当前:
```python
@dataclass
class ParsedDocument:
    filename: str
    sections: list[Section]
    raw_text: str  # full text for fallback splitting
```

修改为:
```python
@dataclass
class ParsedDocument:
    filename: str
    sections: list[Section]
    raw_text: str  # full text for fallback splitting
    source_type: str = "text"       # 新增: text | markdown | docx | pdf
    metadata: dict = field(default_factory=dict)  # 新增: parser 元信息
```

**注意**: 需要 `from dataclasses import dataclass, field` — 当前 imports 已有 `field` (line 3)。

#### 1.2 扩展 Document (models.py:72-87)

在 `updated_at` 之前插入两个新字段:
```python
    source_file_path: str | None = None    # 新增 — 原文件磁盘路径
    source_filename: str | None = None     # 新增 — 原始文件名
```

插入位置: 在 `error_message` 之前（即 line 84 `chunk_count` 之后），或紧跟 `updated_at` 之前。**推荐放在 `error_message` 之前**，因为和现有字段逻辑分组更自然。

最终 Document:
```python
@dataclass
class Document:
    doc_id: str
    kb_id: str
    filename: str
    file_hash: str
    file_size: int
    content_type: str
    content: str
    status: DocStatus = DocStatus.PROCESSING
    chunk_count: int = 0
    source_file_path: str | None = None    # 新增
    source_filename: str | None = None     # 新增
    error_message: str | None = None
    uploaded_at: datetime | None = None
    updated_at: datetime | None = None
```

#### 1.3 新增 FileStoragePort (ports.py, 在 ParserPort 之后)

在 `ports.py` 中，`ParserPort` 协议之后（line 82 之后）新增:

```python
class FileStoragePort(Protocol):
    """文件存储端口 — 二进制文件暂存与读取。"""
    async def save(self, tenant_id: str, doc_id: str,
                   filename: str, content: bytes) -> str: ...
    async def read(self, path: str) -> bytes: ...
    async def delete(self, path: str) -> None: ...
```

#### 1.4 新增 DOCUMENT_PARSE_FAILED (errors.py)

在 `errors.py` line 69 `FEEDBACK_INVALID_SCORE` 之后、`# 数据库与存储` 注释之前插入:

```python
    DOCUMENT_PARSE_FAILED = (20023, 422, "文档解析失败")
```

### 测试要求

修改 `tests/unit/domain/test_models.py`，新增两个测试:

```python
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

同时，**必须检查**并修复因 ParsedDocument 字段变更导致的其他测试文件失败:
- `tests/unit/application/test_upload_doc.py` — mock_parser 返回的 ParsedDocument
- `tests/unit/application/test_indexing_service.py` — 同上
- `tests/unit/adapters/test_parser.py` — 同上

由于新字段有默认值，大多数测试不需要修改（dataclass 默认值自动填充）。但任何显式构造 `ParsedDocument(...)` 并做等值比较（`==`）的测试可能需要更新。

### 测试命令

```bash
# 单元测试 — 领域模型
pytest tests/unit/domain/test_models.py -v

# 关联测试 — 确保不过度破坏
pytest tests/unit/application/test_upload_doc.py tests/unit/application/test_indexing_service.py tests/unit/adapters/test_parser.py -v
```

### Commit

```bash
git add src/ragnexus/domain/models.py src/ragnexus/domain/ports.py src/ragnexus/core/errors.py tests/unit/domain/test_models.py
git commit -m "feat: extend domain models for multi-format parsing"
```

## 全局约束（来自计划）

- **零破坏**: `.md`/`.txt` 上传行为完全不变
- `source_type` 复用 `content_type` 字段，**不新增数据库列**
- 不改切块层、检索层、租户/配额系统
- 中文注释和 docstring

## 当前源文件

### models.py 第 1-88 行
```python
"""领域模型 — 纯 dataclass，无框架依赖。"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any


class DocStatus(IntEnum):
    """文档索引状态枚举 — 与数据库 INTEGER 字段映射。"""
    SUCCESS = 1
    PROCESSING = 2
    FAILED = 3


@dataclass
class ParsedDocument:
    filename: str
    sections: list[Section]
    raw_text: str  # full text for fallback splitting


@dataclass
class Document:
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

### ports.py 第 79-83 行
```python
class ParserPort(Protocol):
    """文档解析。骨架实现: MarkdownAndTextParser。"""
    async def parse(self, content: bytes, filename: str) -> ParsedDocument: ...
```

### errors.py 第 66-70 行
```python
    # 反馈 (20020~20029)
    FEEDBACK_SERVICE_UNAVAILABLE = (20020, 503, "反馈服务不可用")
    FEEDBACK_UNAUTHORIZED = (20021, 403, "无权操作该反馈记录")
    FEEDBACK_INVALID_SCORE = (20022, 422, "评分超出允许范围")
    # 数据库与存储 (30000~30999)
```

## 回报要求

1. **状态**: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
2. **RED 证据**: TDD 模式 — 先写失败测试，运行命令 + 失败输出摘要
3. **GREEN 证据**: 实现后测试通过，运行命令 + 通过输出摘要
4. **Commit**: 完整的 commit hash
5. **变更文件**: 列表
6. **顾虑**: 如有
