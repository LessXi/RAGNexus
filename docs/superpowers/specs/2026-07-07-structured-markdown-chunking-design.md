---
comet_change: structured-markdown-chunking
role: technical-design
canonical_spec: openspec
---

# 结构化 Markdown 切块 — 技术设计

## 1. 问题与动机

RAGNexus 当前索引侧使用 `heading_aware_split()` 做基础标题分节 + 固定窗口二次切，不感知文档内部结构。这导致三类典型问题：

- **标题截断**：切块边界落在 `## 退款时效` 中间 → chunk 语义残缺
- **跨节混入**：chunk 从上一节末尾延伸到下一节开头 → embedding 模糊
- **表格拦腰切断**：表头与数据行分离 → 数据行失去语义上下文

检索侧（调试台、词表、query 改写、profile、RAGAS 测评）已充分优化，索引侧切块精度是当前最大瓶颈。

## 2. 设计方案

### 2.1 整体架构

```
文档上传 → UploadDocumentUseCase → Celery Worker
                                        ↓
                              IndexingService.execute(doc_id)
                                        ↓
                              读取 doc.content (str)
                                        ↓ 按扩展名分流
                    ┌───────────────────┴───────────────────┐
                    ↓ .md                                    ↓ .txt
        structchunk.chunk()                          fixed_size_split()
        (hierarchical algorithm,                    (字符窗口 + overlap,
         table preservation,                         chunk_type="text",
         code block preservation)                    heading_path="")
                    ↓                                       ↓
        list[MarkdownChunk]                        list[str]
                    ↓                                       ↓
        chunk_markdown() bridge ────────────────────────────┘
        · metadata 映射 (heading_path, chunk_type)
        · table_part 后处理
        · 保留 heading/heading_level 向后兼容
                    ↓
        list[dict] → Embedding → 向量 → Chunk dataclass
                    ↓
        双写 pgvector + ES (metadata JSONB 透传新字段)
                    ↓
        API /v1/rag:retrieve → 响应 hits[].metadata 透传
                    ↓
        前端 retrieve.tsx: 展示 heading_path + chunk_type
```

### 2.2 核心模块

#### chunk_markdown() Bridge

`src/ragnexus/infra/structchunk_bridge.py` — structchunk 与 IndexingService 之间的薄适配层：

```python
def chunk_markdown(
    content: str,
    max_chars: int = 1500,
    table_max_rows: int = 10,
) -> list[dict]:
    """结构化 Markdown 切块，返回 IndexingService 兼容的 dict 列表。

    每个 dict 含:
    - text: str          — chunk 正文
    - heading_path: str  — 标题层级路径 (如 "H1 / H2")
    - chunk_type: str    — section | table | code | list
    - table_part: int    — 大表分组序号 (仅表格 chunk)
    - heading: str       — 最近标题文本 (向后兼容)
    - heading_level: int — 标题层级 (向后兼容)
    """
    chunks = structchunk.chunk(
        content,
        algorithm="hierarchical",
        max_chars=max_chars,
        preserve_table_header=True,
        sub_split_table=True,
    )
    # metadata 映射 + table_part 后处理
    return _enrich_chunks(chunks, table_max_rows)
```

#### metadata 映射规则

| structchunk 字段 | RAGNexus 字段 | 转换规则 |
|-----------------|--------------|---------|
| `header_breadcrumb: ["# H1", "## H2"]` | `heading_path: "H1 / H2"` | 去 `#` 标记符，` / ` 连接 |
| `source_element_type: "paragraph"` | `chunk_type: "section"` | 段落 → section |
| `source_element_type: "table"` | `chunk_type: "table"` | 直通 |
| `source_element_type: "code"` | `chunk_type: "code"` | 直通 |
| `source_element_type: "list"` | `chunk_type: "list"` | 直通 |
| `.txt` 回退 | `chunk_type: "text"`, `heading_path: ""` | 纯文本标识 |
| `header_breadcrumb[-1]` | `heading: "H2"` | 向后兼容 |
| 对应 header level | `heading_level: 2` | 向后兼容 |

#### table_part 后处理

bridge 层遍历 chunk 列表，对连续 `chunk_type="table"` 的 chunk 自增编号 `table_part=1, 2, 3...`。遇到非 table chunk 时重置计数器。此逻辑不侵入 structchunk 源码。

### 2.3 IndexingService 改造

`execute()` 方法中 chunker 调用从：

```python
# 旧: ParsedDocument → heading_aware_split
parsed = await self._parser.parse(doc.content.encode(), doc.filename)
chunk_dicts = self._chunker(parsed, max_chars=..., overlap=...)
```

变为：

```python
# 新: 按扩展名分流，直接消费 raw string
if doc.filename.endswith(".md"):
    chunk_dicts = chunk_markdown(doc.content, max_chars=self._chunk_max_chars)
else:
    # .txt 回退: 保留 Parser → fixed_size_split
    parsed = await self._parser.parse(doc.content.encode(), doc.filename)
    chunk_dicts = fixed_size_split_wrapper(parsed, max_chars=..., overlap=...)
```

metadata 构建从手动 `heading`/`heading_level` 变为透传 bridge 返回的全部字段：

```python
metadata = {
    **common_meta,
    "chunk_index": i,
    "heading_path": cd.get("heading_path", ""),
    "chunk_type": cd.get("chunk_type", "section"),
    "heading": cd.get("heading"),           # 向后兼容
    "heading_level": cd.get("heading_level", 0),  # 向后兼容
}
if cd.get("table_part"):
    metadata["table_part"] = cd["table_part"]
```

### 2.4 DI 容器改造

`src/ragnexus/di.py` 的 `_async_build_services()`:

```python
# 旧
from ragnexus.domain.chunking import heading_aware_split
indexing_svc = IndexingService(..., chunker=heading_aware_split, ...)

# 新
from ragnexus.infra.structchunk_bridge import chunk_markdown
indexing_svc = IndexingService(..., chunker=chunk_markdown, ...)
```

## 3. Reindex 设计

### 3.1 单文档强制 reindex

`DocumentReindexUseCase.execute()` 状态检查：

```python
# 旧: 仅 FAILED 允许
if doc.status != DocStatus.FAILED:
    raise AppError(...)

# 新: 仅 PROCESSING 拒绝
if doc.status == DocStatus.PROCESSING:
    raise AppError(ErrorCode.RESOURCE_CONFLICT, "文档正在处理中，请稍后重试")
```

### 3.2 批量 reindex 脚本

`scripts/reindex_knowledge_base.py` 流程：

```
参数解析 (--kb-id 必填, --tenant-id 可选, --document-id 可多次)
  ↓
连接 DB (asyncpg) 查询 kb 下 status=SUCCESS 的文档
  ↓
for each document:
  1. purge_document_chunks(doc_id)  — 清除 pgvector + ES
  2. UPDATE documents SET status=PROCESSING
  3. index_document_task.delay(doc_id)
  4. 打印进度
  ↓ 异常处理
  - 单篇失败: 记录 doc_id，continue
  - PROCESSING 文档: skip
  ↓
打印统计: success=N, failed=M, skipped=K
```

脚本直连 DB 和 Celery，不需要 HTTP API Key。原文从 `documents.content` 读取。

## 4. 前端改造

`admin/src/pages/retrieve.tsx`：chunk 卡片 content 折叠区上方新增一行：

```tsx
{(hit.metadata?.heading_path || hit.metadata?.chunk_type) && (
  <div className="chunk-meta-row">
    {hit.metadata.heading_path && (
      <span>所属章节：{hit.metadata.heading_path}</span>
    )}
    {hit.metadata.chunk_type && (
      <span>块类型：{hit.metadata.chunk_type}</span>
    )}
  </div>
)}
```

仅当字段有值时显示，不影响无结构化切块的旧 chunk 展示。

## 5. 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CHUNK_MAX_CHARS` | 1500 | chunk 最大字符数 |
| `CHUNK_OVERLAP` | 50 | .txt 回退时的重叠字符数 |
| `TABLE_MAX_ROWS_PER_CHUNK` | 10 | 大表每组最多数据行数 |

## 6. 文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/ragnexus/infra/__init__.py` | 新建 | infra 包初始化 |
| `src/ragnexus/infra/structchunk/` | 新建 | 拷贝 .tmp/structchunk_audit/src/structchunk/ |
| `src/ragnexus/infra/structchunk_bridge.py` | 新建 | chunk_markdown 封装 + metadata 映射 |
| `src/ragnexus/domain/chunking.py` | 修改 | heading_aware_split 标记废弃 |
| `src/ragnexus/application/indexing_service.py` | 修改 | 分流逻辑 + metadata 透传 |
| `src/ragnexus/di.py` | 修改 | chunker 注入切换 |
| `src/ragnexus/application/document_reindex_uc.py` | 修改 | 状态检查放宽 |
| `src/ragnexus/config.py` | 修改 | 新增 TABLE_MAX_ROWS_PER_CHUNK |
| `scripts/reindex_knowledge_base.py` | 新建 | 批量 reindex 脚本 |
| `admin/src/pages/retrieve.tsx` | 修改 | 章节/类型展示 |

## 7. 风险与边界

| 风险 | 概率 | 缓解 |
|------|------|------|
| structchunk 兼容性 | 低 | 纯 Python，拷贝核心 .py 文件，跑其 300+ 测试 |
| chunk 数量暴增 | 中 | reindex 后对比 chunk_count，调整 CHUNK_MAX_CHARS |
| reindex 期间不可检索 | 中 | 建议低峰执行，单篇失败不阻断 |
| 旧 chunk 无新字段 | — | 向下兼容，API 返回 null/空，前端仅 show on present |
| 大表 table_part 编号错位 | 低 | bridge 层仅对连续 table chunk 编号 |
