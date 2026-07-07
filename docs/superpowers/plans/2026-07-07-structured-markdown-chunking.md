# 结构化 Markdown 切块 — 实施计划

> **For agentic workers:** 使用 subagent-driven-development 或 executing-plans 按任务执行。步骤使用 `- [ ]` 勾选语法。

**Goal:** 将 RAGNexus 索引侧从固定字符切块升级为结构化 Markdown 切块，集成 structchunk 库，扩展 reindex 能力，增强调试台展示。

**Architecture:** `.md` 文档直连 structchunk（hierarchical 算法）绕过 Parser，`.txt` 保留 fixed_size_split 回退。chunk_markdown bridge 封装 metadata 映射（heading_path, chunk_type, table_part）。reindex 放宽状态检查 + 新增批量脚本。前端 retrieve.tsx 新增一行展示。

**Tech Stack:** Python 3.12+, structchunk (内部拷贝), asyncpg, Celery, React/TypeScript

**Design Doc:** `docs/superpowers/specs/2026-07-07-structured-markdown-chunking-design.md`
**Change:** `structured-markdown-chunking`
**Base Ref:** `be950c9693d9a835abae68c033456d57f654d5a5`

## Global Constraints

- 不破坏现有 .txt 纯文本文档上传流程
- API 响应新增字段向下兼容（null/空值不影响旧 chunk）
- 代码注释和 docstring 使用中文
- 每个 task 独立可测试、独立可提交
- TDD: 先写失败测试 → 最小实现 → 验证通过 → 提交

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `src/ragnexus/infra/__init__.py` | 新建 | infra 包初始化 |
| `src/ragnexus/infra/structchunk/` | 新建 | 拷贝 .tmp/structchunk_audit/src/structchunk/ 核心模块 |
| `src/ragnexus/infra/structchunk_bridge.py` | 新建 | chunk_markdown() 封装：metadata 映射 + table_part 后处理 |
| `src/ragnexus/domain/chunking.py` | 修改 | heading_aware_split 标记废弃 |
| `src/ragnexus/application/indexing_service.py` | 修改 | 分流逻辑（.md→structchunk, .txt→fixed_size_split）+ metadata 构建 |
| `src/ragnexus/di.py` | 修改 | chunker 注入切换 |
| `src/ragnexus/application/document_reindex_uc.py` | 修改 | 状态检查从 != FAILED 改为 == PROCESSING 拒绝 |
| `src/ragnexus/config.py` | 修改 | 新增 TABLE_MAX_ROWS_PER_CHUNK |
| `scripts/reindex_knowledge_base.py` | 新建 | 批量 reindex 脚本 |
| `admin/src/pages/retrieve.tsx` | 修改 | chunk 卡片新增章节/类型展示行 |
| `tests/unit/infra/test_structchunk_bridge.py` | 新建 | bridge metadata 映射测试 |
| `tests/unit/application/test_indexing_service.py` | 修改 | 更新 chunker mock，验证分流 |
| `tests/unit/application/test_document_reindex_uc.py` | 修改 | SUCCESS 可 reindex，PROCESSING 拒绝 |

---

### Task 1: structchunk 库集成

**Files:**
- Create: `src/ragnexus/infra/__init__.py`
- Create: `src/ragnexus/infra/structchunk/` (拷贝核心模块)

**Interfaces:**
- Produces: `src/ragnexus/infra.structchunk.chunk(content, algorithm="hierarchical", max_chars=1500)` → `list[MarkdownChunk]`

- [ ] **Step 1: 拷贝 structchunk 核心模块**

```bash
cp -r .tmp/structchunk_audit/src/structchunk/* src/ragnexus/infra/structchunk/
```

- [ ] **Step 2: 创建 infra 包初始化文件**

`src/ragnexus/infra/__init__.py`:
```python
"""基础设施模块 — 第三方库集成和底层工具。"""
```


- [ ] **Step 2b: 运行 structchunk 自有测试验证兼容性**

```bash
uv run pytest src/ragnexus/infra/structchunk/ -v --tb=short 2>&1 | tail -20
```
Expected: 全部通过或仅有少量与项目环境无关的 skip
- [ ] **Step 3: 验证 structchunk 可导入**

```bash
uv run python -c "from ragnexus.infra.structchunk import chunk, MarkdownChunk; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: 验证 structchunk 基本功能**

```bash
uv run python -c "
from ragnexus.infra.structchunk import chunk
chunks = chunk('# H1\n\n## H2\n\ncontent', algorithm='hierarchical', max_chars=500)
print(len(chunks), chunks[0].metadata.header_breadcrumb)
"
```
Expected: 输出 chunk 数量和面包屑列表

- [ ] **Step 5: Commit**

```bash
git add src/ragnexus/infra/
git commit -m "feat(chunking): integrate structchunk library into infra layer"
```

---

### Task 2: chunk_markdown bridge 封装

**Files:**
- Create: `src/ragnexus/infra/structchunk_bridge.py`

**Interfaces:**
- Produces: `chunk_markdown(content: str, max_chars: int = 1500, table_max_rows: int = 10) -> list[dict]`
- 每个 dict 含: `text`, `heading_path`, `chunk_type`, `table_part`(可选), `heading`, `heading_level`

- [ ] **Step 1: 写失败测试**

`tests/unit/infra/test_structchunk_bridge.py`:
```python
"""structchunk bridge 元数据映射测试。"""
import pytest
from ragnexus.infra.structchunk_bridge import chunk_markdown


class TestChunkMarkdown:
    def test_heading_path_from_breadcrumb(self):
        """header_breadcrumb → heading_path 映射正确，去 # 以 / 连接。"""
        content = "# 平台交易规则\n\n## 退款时效\n\n退款需在7日内申请。"
        chunks = chunk_markdown(content, max_chars=500)
        assert len(chunks) >= 1
        assert chunks[0]["heading_path"] == "平台交易规则 / 退款时效"

    def test_chunk_type_section(self):
        """普通段落 chunk_type 为 section。"""
        content = "## 说明\n\n这是一段普通文本。"
        chunks = chunk_markdown(content, max_chars=500)
        assert chunks[0]["chunk_type"] == "section"

    def test_chunk_type_table(self):
        """表格 chunk_type 为 table。"""
        content = "## 价格\n\n| 商品 | 价格 |\n|------|------|\n| A | 10 |"
        chunks = chunk_markdown(content, max_chars=500)
        table_chunks = [c for c in chunks if c["chunk_type"] == "table"]
        assert len(table_chunks) >= 1
        assert "商品" in table_chunks[0]["text"]

    def test_backward_compat_heading(self):
        """保留 heading 和 heading_level 向后兼容。"""
        content = "## 测试\n\n内容。"
        chunks = chunk_markdown(content, max_chars=500)
        assert chunks[0]["heading"] == "测试"
        assert chunks[0]["heading_level"] == 2

    def test_txt_fallback_no_heading_path(self):
        """纯文本无标题时 heading_path 为空。"""
        # 无标题 markdown 文本
        content = "这是纯文本内容，没有任何标题标记。"
        chunks = chunk_markdown(content, max_chars=500)
        assert chunks[0]["heading_path"] == ""

    def test_table_part_increment(self):
        """大表分组时 table_part 递增。"""
        # 构造一个超过 max_chars 的大表（低 max_chars 强制分组）
        header = "| 列1 | 列2 | 列3 | 列4 | 列5 |\n|------|------|------|------|------|\n"
        rows = "\n".join([f"| r{i} | data{i} | x{i} | y{i} | z{i} |" for i in range(20)])
        content = f"## 大表\n\n{header}{rows}"
        chunks = chunk_markdown(content, max_chars=500, table_max_rows=5)
        table_chunks = [c for c in chunks if c.get("table_part")]
        assert len(table_chunks) >= 2
        assert table_chunks[0]["table_part"] == 1
        assert table_chunks[1]["table_part"] == 2

    def test_horizontal_rule_filtered(self):
        """独立 --- 行不出现在任何 chunk 中。"""
        content = "## 第一节\n\n内容A\n\n---\n\n## 第二节\n\n内容B"
        chunks = chunk_markdown(content, max_chars=500)
        for c in chunks:
            assert "---" not in c["text"] or c["heading_path"]  # --- 可能与分隔线混淆，至少不出现在正文孤立
```

- [ ] **Step 2: 运行测试验证失败**

```bash
uv run pytest tests/unit/infra/test_structchunk_bridge.py -v
```
Expected: FAIL (chunk_markdown 尚未实现)

- [ ] **Step 3: 实现 chunk_markdown**

`src/ragnexus/infra/structchunk_bridge.py`:
```python
"""structchunk 与 IndexingService 之间的薄适配层。

封装 metadata 映射（heading_path, chunk_type, table_part）
和 table_part 后处理逻辑。
"""

from ragnexus.infra.structchunk import chunk as _structchunk_chunk


def chunk_markdown(
    content: str,
    max_chars: int = 1500,
    table_max_rows: int = 10,
) -> list[dict]:
    """结构化 Markdown 切块，返回 IndexingService 兼容的 dict 列表。

    每个 dict 含:
    - text: str          — chunk 正文
    - heading_path: str  — 标题层级路径 (如 "H1 / H2")
    - chunk_type: str    — section | table | code | list | text
    - table_part: int    — 大表分组序号 (仅表格 chunk，可选)
    - heading: str       — 最近标题文本 (向后兼容)
    - heading_level: int — 标题层级 (向后兼容)
    """
    chunks = _structchunk_chunk(
        content,
        algorithm="hierarchical",
        max_chars=max_chars,
        preserve_table_header=True,
        sub_split_table=True,
    )

    result: list[dict] = []
    table_part_counter = 0

    for ch in chunks:
        md = ch.metadata

        # ── heading_path: 去 # 标记符，以 / 连接 ──
        breadcrumb_texts = [
            h.lstrip("#").strip() for h in md.header_breadcrumb
        ]
        heading_path = " / ".join(breadcrumb_texts) if breadcrumb_texts else ""

        # ── chunk_type: source_element_type 映射 ──
        elem_type = (md.source_element_type or "paragraph").lower()
        type_map = {
            "paragraph": "section",
            "table": "table",
            "code": "code",
            "list": "list",
        }
        chunk_type = type_map.get(elem_type, "section")

        # ── heading / heading_level: 向后兼容 ──
        last_heading = ""
        last_level = 0
        if md.header_path:
            last = md.header_path[-1]
            last_heading = last.text
            last_level = last.level
        elif md.header_breadcrumb:
            # fallback: 从 breadcrumb 取最后一个
            last = md.header_breadcrumb[-1].lstrip("#").strip()
            last_heading = last
            last_level = md.header_breadcrumb[-1].count("#")

        piece: dict = {
            "text": ch.content,
            "heading_path": heading_path,
            "chunk_type": chunk_type,
            "heading": last_heading,
            "heading_level": last_level,
        }

        # ── table_part: 连续 table chunk 自增编号 ──
        if chunk_type == "table":
            table_part_counter += 1
            piece["table_part"] = table_part_counter
        else:
            table_part_counter = 0

        result.append(piece)

    return result
```

- [ ] **Step 4: 运行测试验证通过**

```bash
uv run pytest tests/unit/infra/test_structchunk_bridge.py -v
```
Expected: ALL PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ragnexus/infra/structchunk_bridge.py tests/unit/infra/test_structchunk_bridge.py
git commit -m "feat(chunking): add chunk_markdown bridge with metadata mapping"
```

---

### Task 3: 配置 TABLE_MAX_ROWS_PER_CHUNK

**Files:**
- Modify: `src/ragnexus/config.py`

**Interfaces:**
- Produces: `Settings.TABLE_MAX_ROWS_PER_CHUNK: int = 10`

- [ ] **Step 1: 添加配置项**

在 `src/ragnexus/config.py` 的 `Settings` 类中新增:

```python
# 结构化切块配置
TABLE_MAX_ROWS_PER_CHUNK: int = 10  # 大表每组最多数据行数
```

- [ ] **Step 2: 验证配置可读取**

```bash
uv run python -c "from ragnexus.config import get_settings; s = get_settings(); print(s.TABLE_MAX_ROWS_PER_CHUNK)"
```
Expected: `10`

- [ ] **Step 3: Commit**

```bash
git add src/ragnexus/config.py
git commit -m "feat(chunking): add TABLE_MAX_ROWS_PER_CHUNK config"
```

---

### Task 4: 废弃旧 chunker

**Files:**
- Modify: `src/ragnexus/domain/chunking.py`

**Interfaces:**
- 保留: `fixed_size_split(text, max_chars, overlap) -> list[str]`
- 废弃: `heading_aware_split(parsed, max_chars, overlap) -> list[dict]`

- [ ] **Step 1: 标记 heading_aware_split 为废弃**

在 `heading_aware_split` 函数上方添加 deprecation warning:

```python
import warnings

def heading_aware_split(
    parsed: ParsedDocument, max_chars: int = 1500, overlap: int = 50
) -> list[dict]:
    """[DEPRECATED] 按 # 标题分割 — 请使用 chunk_markdown 代替。

    此函数将在结构化切块稳定后移除。
    """
    warnings.warn(
        "heading_aware_split is deprecated, use chunk_markdown instead",
        DeprecationWarning,
        stacklevel=2,
    )
    # ... 保留原有实现 ...
```

- [ ] **Step 2: 验证 fixed_size_split 仍可正常工作**

```bash
uv run python -c "
from ragnexus.domain.chunking import fixed_size_split
chunks = fixed_size_split('hello world ' * 100, 50, 10)
print(len(chunks), len(chunks[0]))
assert all(len(c) <= 50 for c in chunks)
print('OK')
"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/ragnexus/domain/chunking.py
git commit -m "refactor(chunking): deprecate heading_aware_split, retain fixed_size_split"
```

---

### Task 5: IndexingService 分流改造

**Files:**
- Modify: `src/ragnexus/application/indexing_service.py`
- Modify: `tests/unit/application/test_indexing_service.py`

**Interfaces:**
- Consumes: `chunk_markdown(content, max_chars, table_max_rows) -> list[dict]`
- Consumes: `fixed_size_split(text, max_chars, overlap) -> list[str]`
- Modifies: `IndexingService.execute()` 内 chunker 调用

- [ ] **Step 1: 更新测试**

修改 `tests/unit/application/test_indexing_service.py` 中 chunker 相关测试，mock 改为返回含新字段的 dict:

```python
@pytest.fixture
def mock_md_chunks():
    """模拟 structchunk chunk_markdown 返回值。"""
    return [
        {
            "text": "## 第一节\n\n这是第一节的内容。",
            "heading_path": "测试 / 第一节",
            "chunk_type": "section",
            "heading": "第一节",
            "heading_level": 2,
        },
        {
            "text": "## 第二节\n\n这是第二节的内容。",
            "heading_path": "测试 / 第二节",
            "chunk_type": "section",
            "heading": "第二节",
            "heading_level": 2,
        },
    ]
```

更新测试用例验证 metadata 透传 `heading_path` 和 `chunk_type`。

- [ ] **Step 2: 运行测试验证失败**

```bash
uv run pytest tests/unit/application/test_indexing_service.py -v -x
```
Expected: FAIL（IndexingService 尚未调用新 chunker）

- [ ] **Step 3: 实现分流逻辑**

修改 `IndexingService.execute()` 中 chunker 调用部分:

```python
# 2. Chunk — 按扩展名分流
if doc.filename.endswith(".md"):
    from ragnexus.infra.structchunk_bridge import chunk_markdown
    from ragnexus.config import get_settings
    settings = get_settings()
    chunk_dicts = chunk_markdown(
        doc.content,
        max_chars=self._chunk_max_chars,
        table_max_rows=settings.TABLE_MAX_ROWS_PER_CHUNK,
    )
else:
    # .txt 回退：保留 Parser → fixed_size_split
    parsed = await self._parser.parse(doc.content.encode(), doc.filename)
    texts = fixed_size_split(
        parsed.raw_text, self._chunk_max_chars, self._chunk_overlap
    )
    chunk_dicts = [
        {
            "text": t,
            "heading_path": "",
            "chunk_type": "text",
            "heading": None,
            "heading_level": 0,
        }
        for t in texts
        if t.strip()
    ]
```

metadata 构建改为透传新字段:

```python
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
            "heading_path": cd.get("heading_path", ""),
            "chunk_type": cd.get("chunk_type", "section"),
            "heading": cd.get("heading"),
            "heading_level": cd.get("heading_level", 0),
            **({"table_part": cd["table_part"]} if cd.get("table_part") else {}),
        },
    )
    for i, cd in enumerate(chunk_dicts)
]
```

- [ ] **Step 4: 运行测试验证通过**

```bash
uv run pytest tests/unit/application/test_indexing_service.py -v -x
```
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/ragnexus/application/indexing_service.py tests/unit/application/test_indexing_service.py
git commit -m "feat(chunking): route .md to structchunk, .txt to fixed_size_split in IndexingService"
```

---

### Task 6: DI 容器更新

**Files:**
- Modify: `src/ragnexus/di.py`

- [ ] **Step 1: 切换 chunker 注入**

将 `_async_build_services()` 中的 chunker 注入从 `heading_aware_split` 改为使用 `IndexingService` 内部的分流逻辑（chunker 参数不再需要外部传入，IndexingService 内部自行决策）。

实际上 `di.py` 中 chunker 仍传入 `IndexingService.__init__`，但 `execute()` 内部不再使用 `self._chunker`，改为直接调用 `chunk_markdown` 或 `fixed_size_split`。保留 `chunker` 参数兼容性但不再在 .md 路径使用。

```python
# di.py — 保留 chunker 参数但不强制类型（向后兼容）
indexing_svc = IndexingService(
    doc_repo=doc_repo,
    parser=parser,
    embedder=embedder,
    chunker=None,  # IndexingService 内部自行分流
    store=store,
    ...
)
```

同时在 `IndexingService.__init__` 中让 `chunker` 参数变为可选：

```python
def __init__(
    self,
    ...,
    chunker: Callable[..., list[dict]] | None = None,
    ...
) -> None:
```

- [ ] **Step 2: 验证 Worker 可正常启动**

```bash
uv run python -c "
import asyncio
from ragnexus.config import get_settings
from ragnexus.di import build_indexing_services_async
async def test():
    svc, _, _ = await build_indexing_services_async(get_settings())
    print('IndexingService created OK')
asyncio.run(test())
"
```

- [ ] **Step 3: Commit**

```bash
git add src/ragnexus/di.py
git commit -m "refactor(chunking): update DI container for structchunk routing"
```

---

### Task 7: 单文档 reindex 扩展

**Files:**
- Modify: `src/ragnexus/application/document_reindex_uc.py`
- Modify: `tests/unit/application/test_document_reindex_uc.py`

- [ ] **Step 1: 更新测试**

`tests/unit/application/test_document_reindex_uc.py` 新增:

```python
class TestReindexSuccessDoc:
    """SUCCESS 状态文档应允许强制 reindex。"""

    async def test_success_doc_can_reindex(self):
        """status=SUCCESS 的文档可调用 reindex。"""
        # mock doc with SUCCESS status
        doc = MagicMock(status=DocStatus.SUCCESS, kb_id="kb_1")
        kb = MagicMock(tenant_id="tenant_1")
        doc_repo = MagicMock()
        doc_repo.get = AsyncMock(return_value=doc)
        doc_repo.update_status = AsyncMock()
        kb_repo = MagicMock()
        kb_repo.get = AsyncMock(return_value=kb)
        uc = DocumentReindexUseCase(doc_repo, kb_repo)
        result = await uc.execute("doc_1", "tenant_1")
        assert result["doc_id"] == "doc_1"
        assert result["status"] == "processing"
        doc_repo.update_status.assert_called_once()

    async def test_processing_doc_rejected(self):
        """status=PROCESSING 的文档应拒绝 reindex。"""
        doc = MagicMock(status=DocStatus.PROCESSING, kb_id="kb_1")
        kb = MagicMock(tenant_id="tenant_1")
        doc_repo = MagicMock()
        doc_repo.get = AsyncMock(return_value=doc)
        kb_repo = MagicMock()
        kb_repo.get = AsyncMock(return_value=kb)
        uc = DocumentReindexUseCase(doc_repo, kb_repo)
        with pytest.raises(AppError) as exc:
            await uc.execute("doc_1", "tenant_1")
        assert exc.value.code == ErrorCode.RESOURCE_CONFLICT
```

- [ ] **Step 2: 运行测试验证失败**

```bash
uv run pytest tests/unit/application/test_document_reindex_uc.py -v -x
```
Expected: FAIL (test_success_doc_can_reindex 应失败，当前仅允许 FAILED)

- [ ] **Step 3: 放宽状态检查**

```python
# 旧代码
if doc.status != DocStatus.FAILED:
    raise AppError(...)

# 新代码
if doc.status == DocStatus.PROCESSING:
    raise AppError(
        ErrorCode.RESOURCE_CONFLICT,
        "文档正在处理中，请稍后重试",
        errors=[{"field": "status", "reason": f"当前状态: {doc.status.name}"}],
    )
```

- [ ] **Step 4: 运行测试验证通过**

```bash
uv run pytest tests/unit/application/test_document_reindex_uc.py -v -x
```
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/ragnexus/application/document_reindex_uc.py tests/unit/application/test_document_reindex_uc.py
git commit -m "feat(reindex): allow SUCCESS documents to force reindex"
```

---

### Task 7b: reindex 路由文档更新

**Files:**
- Modify: `src/ragnexus/adapters/http/document_router.py`

**Interfaces:**
- Consumes: `DocumentReindexUseCase` (已扩展)

- [ ] **Step 1: 更新路由描述和响应说明**

在 `POST /documents/{id}/reindex` 路由的 docstring 和响应模型中，将"仅 FAILED 状态允许"改为"SUCCESS 和 FAILED 状态允许，PROCESSING 拒绝"。

```python
@router.post("/v1/documents/{doc_id}/reindex")
async def reindex_document(
    doc_id: str,
    current_tenant: TenantContext = Depends(get_current_tenant),
):
    """重新索引文档。

    允许 SUCCESS 和 FAILED 状态的文档强制重建索引。
    PROCESSING 中的文档将被拒绝。
    """
    result = await reindex_uc.execute(doc_id, current_tenant.tenant_id)
    return {"code": 0, "data": result, "message": "ok"}
```

- [ ] **Step 2: Commit**

- Consumes: `index_document_task` from Celery
```

---

### Task 8: 批量 reindex 脚本

**Files:**
- Create: `scripts/reindex_knowledge_base.py`

**Interfaces:**
- CLI: `--kb-id` (必填), `--tenant-id` (可选), `--document-id` (可多次, 可选)
- Consumes: `index_document_task` from Celery

- [ ] **Step 1: 创建脚本**

`scripts/reindex_knowledge_base.py`:
```python
#!/usr/bin/env python3
"""批量重建知识库索引。

对指定知识库下所有 status=SUCCESS 的文档执行 purge + 重新索引。
单篇失败不阻断其余文档，结束时打印统计。

用法:
    python scripts/reindex_knowledge_base.py --kb-id kb_ecom
    python scripts/reindex_knowledge_base.py --kb-id kb_ecom --document-id doc_aaa
"""

import argparse
import asyncio
import sys

import asyncpg

from ragnexus.config import get_settings
from ragnexus.domain.models import DocStatus
from ragnexus.tasks.indexing import index_document_task


async def main():
    parser = argparse.ArgumentParser(description="批量重建知识库索引")
    parser.add_argument("--kb-id", required=True, help="目标知识库 ID")
    parser.add_argument("--tenant-id", help="租户 ID（可选，不传时从 KB 记录反查）")
    parser.add_argument("--document-id", action="append", default=[],
                        help="指定文档 ID（可多次传入，不传则处理全部）")
    args = parser.parse_args()

    settings = get_settings()
    pool = await asyncpg.create_pool(settings.PG_DSN, min_size=1, max_size=3)

    try:
        # 验证知识库存在
        kb = await pool.fetchrow(
            "SELECT id, name, tenant_id FROM knowledge_bases WHERE id = $1",
            args.kb_id,
        )
        if kb is None:
            print(f"错误: 知识库 {args.kb_id} 不存在")
            sys.exit(1)
        print(f"知识库: {kb['name']} (ID: {kb['id']})")

        # 查询待处理文档
        if args.document_id:
            docs = await pool.fetch(
                "SELECT doc_id, filename, status FROM documents "
                "WHERE kb_id = $1 AND doc_id = ANY($2) AND status = $3",
                args.kb_id, args.document_id, DocStatus.SUCCESS.value,
            )
        else:
            docs = await pool.fetch(
                "SELECT doc_id, filename, status FROM documents "
                "WHERE kb_id = $1 AND status = $2",
                args.kb_id, DocStatus.SUCCESS.value,
            )

        if not docs:
            print("没有需要 reindex 的文档")
            return

        print(f"共 {len(docs)} 篇文档待处理\n")

        success = 0
        failed = 0
        skipped = 0

        for doc in docs:
            doc_id = doc["doc_id"]
            filename = doc["filename"]

            # 二次确认状态（并发下可能变化）
            current = await pool.fetchrow(
                "SELECT status FROM documents WHERE doc_id = $1", doc_id
            )
            if current is None:
                print(f"  [SKIP] {filename}: 文档已不存在")
                skipped += 1
                continue
            if current["status"] != DocStatus.SUCCESS.value:
                print(f"  [SKIP] {filename}: 状态不是 SUCCESS")
                skipped += 1
                continue

            try:
                # 清除旧 chunk: pgvector（直接 SQL DELETE）+ ES（如有 keyword_store）
                await pool.execute("DELETE FROM chunks WHERE doc_id = $1", doc_id)
                # 更新状态
                await pool.execute(
                    "UPDATE documents SET status = $1, error_message = NULL, "
                    "updated_at = NOW() WHERE doc_id = $2",
                    DocStatus.PROCESSING.value, doc_id,
                )
                # 提交 Celery 任务
                index_document_task.apply_async(args=[doc_id], ignore_result=True)
                print(f"  [OK] {filename} → PROCESSING")
                success += 1
            except Exception as e:
                print(f"  [FAIL] {filename}: {e}")
                failed += 1

        print(f"\n--- 完成 ---")
        print(f"已处理: {success} 篇  失败: {failed} 篇  跳过: {skipped} 篇")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 验证脚本语法正确**

```bash
uv run python -c "import py_compile; py_compile.compile('scripts/reindex_knowledge_base.py', doraise=True); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/reindex_knowledge_base.py
git commit -m "feat(reindex): add batch reindex script for knowledge bases"
```

---

### Task 9: 调试台展示增强

**Files:**
- Modify: `admin/src/pages/retrieve.tsx`

- [ ] **Step 1: 添加 chunk 元信息展示行**

在 `retrieve.tsx` 中找到渲染 chunk content 的区域，在 content 折叠区上方新增:

```tsx
{/* chunk 结构元信息 */}
{(hit.metadata?.heading_path || hit.metadata?.chunk_type) && (
  <div style={{
    fontSize: '12px',
    color: '#666',
    marginBottom: '8px',
    padding: '4px 8px',
    background: '#f5f5f5',
    borderRadius: '4px',
    display: 'flex',
    gap: '16px',
  }}>
    {hit.metadata.heading_path && (
      <span>所属章节：{hit.metadata.heading_path}</span>
    )}
    {hit.metadata.chunk_type && (
      <span>块类型：{hit.metadata.chunk_type}</span>
    )}
  </div>
)}
```

- [ ] **Step 2: 验证前端编译通过**

```bash
cd admin && npx tsc --noEmit --pretty 2>&1 | tail -5
```

- [ ] **Step 3: Commit**

```bash
git add admin/src/pages/retrieve.tsx
git commit -m "feat(ui): display heading_path and chunk_type in retrieve debug page"
```

---

### Task 9b: chunking 模块单元测试

**Files:**
- Modify: `tests/unit/domain/test_chunking.py`（如存在）或新建

**Interfaces:**
- Consumes: `fixed_size_split` from `ragnexus.domain.chunking`

- [ ] **Step 1: 编写/更新测试**

验证 `fixed_size_split` 行为不变，`heading_aware_split` 触发 deprecation warning：

```python
"""chunking 模块单元测试。"""
import pytest
import warnings
from ragnexus.domain.chunking import fixed_size_split, heading_aware_split
from ragnexus.domain.models import ParsedDocument, Section


class TestFixedSizeSplit:
    def test_empty_text(self):
        assert fixed_size_split("", 100, 20) == []

    def test_basic_split(self):
        text = "hello world " * 100
        chunks = fixed_size_split(text, 50, 10)
        assert all(len(c) <= 50 for c in chunks)
        assert len(chunks) > 1

    def test_overlap(self):
        text = "abcdefghij" * 10
        chunks = fixed_size_split(text, 30, 5)
        # 验证前一个 chunk 的末尾与后一个 chunk 的开头有重叠
        if len(chunks) >= 2:
            assert chunks[0][-5:] == chunks[1][:5]


class TestHeadingAwareSplitDeprecated:
    def test_deprecation_warning(self):
        parsed = ParsedDocument(
            filename="test.md",
            sections=[Section(heading="Test", level=2, content="content")],
            raw_text="## Test\n\ncontent",
        )
        with pytest.warns(DeprecationWarning, match="heading_aware_split"):
            heading_aware_split(parsed, max_chars=500, overlap=50)
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/unit/domain/test_chunking.py -v
```
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/domain/test_chunking.py
git commit -m "test(chunking): add unit tests for fixed_size_split and deprecation"
```

---

### Task 10: 文档更新

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: README 新增 reindex 小节**

在 README.md 运维部分新增:

```markdown
### 切块策略升级后 reindex

结构化切块策略变更后，已索引的旧文档仍使用旧切法。执行以下命令重建索引：

```bash
# 对整个知识库 reindex
uv run python scripts/reindex_knowledge_base.py --kb-id <kb_id>

# 仅 reindex 指定文档
uv run python scripts/reindex_knowledge_base.py --kb-id <kb_id> --document-id <doc_id>
```

- 建议在低峰期或文档量较小时执行
- reindex 期间对应文档暂时不可检索
- 脚本结束后打印 success/failed/skipped 统计
```

- [ ] **Step 2: AGENTS.md 补充诊断信息**

```markdown
### 结构化切块相关诊断

```bash
# 查看文档的 chunk 类型分布
docker exec ragnexus-db-1 psql -U ragnexus -d ragnexus -c "
SELECT metadata->>'chunk_type' AS type, count(*)
FROM chunks WHERE document_id = '<doc_id>'
GROUP BY 1"

# 查看 heading_path
docker exec ragnexus-db-1 psql -U ragnexus -d ragnexus -c "
SELECT metadata->>'heading_path' AS path, metadata->>'chunk_type' AS type, LEFT(content, 60)
FROM chunks WHERE document_id = '<doc_id>' ORDER BY metadata->>'chunk_index'"
```

- [ ] **Step 3: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: add reindex usage guide and chunking diagnostics"
```

---

### Task 11: 端到端验证

**Files:**
- 无新建文件

- [ ] **Step 1: 运行全部单元测试**

```bash
uv run pytest tests/unit/ -v -x --tb=short
```
Expected: ALL PASS

- [ ] **Step 2: 如果有 Docker 环境，构建并验证**

```bash
docker compose build app && docker compose up -d app
curl -s http://localhost:8000/openapi.json | python3 -c "import json,sys; print(len(json.load(sys.stdin)['paths']))"
```
Expected: 路由数不变（新增字段不影响路由）

- [ ] **Step 3: Commit 最终状态**

```bash
git add -A
git commit -m "test: final integration verification for structured chunking"
```
