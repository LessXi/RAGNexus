# Design: 结构化 Markdown 切块

## Context

**当前状态**：`src/ragnexus/domain/chunking.py` 的 `heading_aware_split()` 基于 `ParsedDocument.sections` 做基础标题分节，不支持表格识别、无 `heading_path` 层级路径、无 `chunk_type` 元数据。`IndexingService` 通过 `di.py` 注入 `chunker`，chunk metadata 只含 `heading` 和 `heading_level`。

**已有资源**：`.tmp/structchunk_audit/` 是一个完整的、有 300+ 测试用例的生产级 Markdown 切块库，功能完全覆盖文档需求：
- `chunk(content, algorithm="hierarchical", max_chars=1500)` — 返回 `list[MarkdownChunk]`
- `MarkdownChunk.content` — chunk 正文
- `MarkdownChunk.metadata.header_breadcrumb` — `["# H1", "## H2"]` 格式，直接映射到 `heading_path`
- `MarkdownChunk.metadata.source_element_type` — `table`/`code`/`list`/`paragraph`，直接映射到 `chunk_type`
- 表格保护：`preserve_table_header=True`，大表 `sub_split_table=True` 时带表头重复

**约束**：
- 不能破坏现有 `.txt` 纯文本文档的上传（需保留回退路径）
- `IndexingService` 的 chunker 签名从 `(ParsedDocument, max_chars, overlap) -> list[dict]` 变为 `(str, **kwargs) -> list[MarkdownChunk]`
- chunks 表 `metadata` 是 JSONB，新增字段向下兼容

## Goals / Non-Goals

**Goals:**
1. 替换 `heading_aware_split` 为基于 `structchunk` 的结构化切块
2. chunk metadata 新增 `heading_path`（`/` 分隔的标题路径）和 `chunk_type`（`section`/`table`/`code`/`list`）
3. 扩展单文档 reindex 支持 SUCCESS 状态
4. 新增批量 reindex 脚本
5. 调试台展示 `heading_path` 和 `chunk_type`

**Non-Goals:**
- 不新增 Word/PDF 解析支持
- 不改 RAGAS 评测脚本
- 不新增 Admin 后台 reindex 页面（脚本即入口）
- 不切换 embedding 模型
- 不修改 `POST /v1/rag:retrieve` 请求/响应的顶层结构

## Decisions

### 决策 1: 使用 structchunk 库而非自己写 MarkdownStructuredSplitter

**选择**: 集成 `.tmp/structchunk_audit/` 为项目依赖，而非按文档描述新建 `MarkdownStructuredSplitter`。

**理由**:
- structchunk 已实现文档描述的全部功能（表格保护、标题层级、代码块保护、元素类型标注、大表分组），且经过完整测试
- 自己写需要 500+ 行代码 + 数十个单测，等同于重复造轮子
- structchunk 的 `ChunkMetadata` 模型（`header_breadcrumb`、`source_element_type`）与需求字段天然对应

**替代方案**:
- ❌ 新建 `MarkdownStructuredSplitter`：文档描述的方案，但 structchunk 是等价甚至更完善的实现
- ❌ 保留 `heading_aware_split` 并追加表格逻辑：旧代码的 ParsedDocument 抽象层（先解析再切）与 structchunk 的原始字符串扫描理念冲突，混合维护成本高

**集成方式**:
- `di.py` 中将 `chunker` 参数改为可选（`None`），`IndexingService.execute()` 内部自行按扩展名分流
- 新增薄封装函数 `chunk_markdown(content: str, max_chars: int, ...) -> list[dict]` 位于 `src/ragnexus/infra/structchunk_bridge.py`

### 决策 2: chunker 接口从 ParsedDocument 切换到纯字符串

**选择**: `IndexingService._chunker` 的签名从 `(ParsedDocument, max_chars, overlap) -> list[dict]` 变为 `(str, max_chars) -> list[dict]`。

**理由**:
- structchunk 内部自己做解析（按行扫描），不需要外部预解析
- MarkdownAndTextParser 的解析变为冗余（structchunk 直接处理原始 markdown）
- 简化调用链：`parser.parse()` 仍用于 .txt 回退，markdown 直接传 `document.content`

**迁移路径**:
1. 新建 `src/ragnexus/infra/structchunk_bridge.py`，暴露 `chunk_markdown(content, max_chars, **kwargs) -> list[dict]`
2. `IndexingService.execute()` 中：markdown 文档调 `chunk_markdown`，.txt 文档回退到 `fixed_size_split`
3. 逐步废弃 `heading_aware_split`（保留为废弃标记，待 reindex 验证后删除）

### 决策 3: metadata 字段映射

```
structchunk ChunkMetadata          →  RAGNexus chunk metadata
────────────────────────────────────────────────────────────
header_breadcrumb: ["# H1","## H2"] → heading_path: "H1 / H2"
source_element_type: "table"        → chunk_type: "table"
source_element_type: "code"         → chunk_type: "code"
source_element_type: "list"         → chunk_type: "list"
source_element_type: "paragraph"    → chunk_type: "section"
header_breadcrumb[-1] if exists     → heading: "H2"（保留向后兼容）
```

`heading_path` 格式：去掉 markdown 标记符 `#` 后以 `/` 连接，如 `"平台交易规则 / 退款时效"`。

大表分组：`table_part` 字段从 structchunk 的 `source_element_position` 或从 chunk_index 推导（需要自定义逻辑），因为 structchunk 目前不直接提供 table_part。

### 决策 4: .txt 纯文本回退策略

**选择**: 在 `IndexingService.execute()` 中按扩展名分流：
- `.md` → `structchunk.chunk(content, algorithm="hierarchical", max_chars=CHUNK_MAX_CHARS)`
- `.txt` → 保留 `fixed_size_split(content, CHUNK_MAX_CHARS, CHUNK_OVERLAP)` 作为回退，`chunk_type="text"`, `heading_path` 为空

**理由**: 纯文本无结构可感知，structchunk 的 hierarchical 算法退化为全文一个大 section 然后 secondary split，与 fixed_size_split 效果相似但多了不必要的解析开销。

### 决策 5: reindex 后文档原文从哪里来

**选择**: 从 `documents.content` 字段读取原文，不要求重新上传文件。

**理由**: 上传时已将完整内容存入 `documents.content`，reindex 时直接读取即可。结构化切块不会改变原文，只需清除旧 chunk 并按新切法重建。

### 决策 6: 调试台展示设计

**选择**: 在 `retrieve.tsx` 的 chunk 卡片中，content 折叠区上方增加一行只读展示：

```
所属章节：平台交易规则 / 退款时效    块类型：table
```

仅当 `heading_path` 或 `chunk_type` 有值时才显示该行，不做复杂 UI。

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| structchunk 库可能有不兼容的依赖或行为 | 先跑其 300+ 测试确认通过，再集成；必要时 fork |
| chunk 数量/大小变化导致向量存储膨胀 | reindex 后对比 chunk_count 变化，必要时调整 CHUNK_MAX_CHARS |
| reindex 期间文档短暂不可检索 | 文档建议低峰期执行，脚本本身是异步 Celery 任务，单篇失败不阻断 |
| 旧 chunk 的 metadata 不含 `heading_path`，检索时该字段为 null | 向下兼容，调试台仅在字段存在时展示 |
| 切换 chunker 后 .txt 文档行为差异 | 保留 `fixed_size_split` 回退，单测覆盖 |

## Data Flow

```
文档上传
  ↓
UploadDocumentUseCase: 存 content → 触发 Celery
  ↓
Celery Worker: IndexingService.execute(doc_id)
  ↓
读取 doc.content (str)
  ↓ 按扩展名分流
  ├─ .md → structchunk.chunk(content, algorithm="hierarchical", max_chars=1500)
  └─ .txt → fixed_size_split(content, max_chars=1500, overlap=50)
  ↓
list[MarkdownChunk] → 转换为 list[dict]（含 heading_path, chunk_type, heading）
  ↓
Embedding → 向量
  ↓
构建 Chunk dataclass → metadata 含 heading_path, chunk_type, heading
  ↓
双写 pgvector + ES
  ↓
API 返回时透传 metadata
  ↓
前端 retrieve.tsx 渲染 heading_path + chunk_type
```

## Affected Files

| 文件 | 变更 |
|------|------|
| `src/ragnexus/domain/chunking.py` | `heading_aware_split` 标记废弃 |
| `src/ragnexus/application/indexing_service.py` | 分流逻辑 + metadata 透传 |
| `src/ragnexus/di.py` | chunker 参数改为可选，IndexingService 内部自行分流 |
| `src/ragnexus/application/document_reindex_uc.py` | 状态检查放宽 |
| `src/ragnexus/adapters/http/document_router.py` | reindex 接口文档更新 |
| `scripts/reindex_knowledge_base.py` | 新建批量 reindex 脚本 |
| `admin/src/pages/retrieve.tsx` | chunk 卡片新增章节和类型展示 |
| `src/ragnexus/infra/structchunk_bridge.py` | 新建 chunk_markdown 封装 + metadata 映射 |
