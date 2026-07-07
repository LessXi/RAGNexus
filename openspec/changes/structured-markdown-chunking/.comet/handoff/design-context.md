# Comet Design Handoff

- Change: structured-markdown-chunking
- Phase: design
- Mode: compact
- Context hash: 0bb8df446f4edd4e564957b7f7afa28ac8e239271847b7e11ea3cc26114ef6aa

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/structured-markdown-chunking/proposal.md

- Source: openspec/changes/structured-markdown-chunking/proposal.md
- Lines: 1-35
- SHA256: cc601508a62c50dccbe540428a7302e41ee5e47cd241b5fc4d2927ff2fe16769

```md
# Proposal: 结构化 Markdown 切块

## Why

当前索引侧已落后于检索侧：无论上传什么文档，都按固定 800 字符滑动窗口一刀切。这导致标题被截断、跨节内容混入同一 chunk、表格被拦腰切断丢失表头——三个问题直接拉低召回质量和 RAGAS 分数。检索侧（调试台、词表、query 改写、profile、RAGAS 测评）的优化已接近天花板，**索引侧的切块精度是当前最大的检索质量瓶颈**。

## What Changes

- **替换切块器**：`heading_aware_split` → `structchunk` 库的结构化切块（按 `#`/`##` 分节、表格整块保留表头、代码块不截断），`###` 三级标题归入上级节
- **新增 chunk 元数据**：每个 chunk 记录 `heading_path`（标题层级路径）和 `chunk_type`（section/table/code/list）
- **扩展单文档 reindex**：`POST /documents/{id}/reindex` 从仅允许 FAILED 状态扩展为允许 SUCCESS 状态强制重建
- **新增批量 reindex 脚本**：`scripts/reindex_knowledge_base.py`，一条命令对指定知识库下所有已索引文档重建索引
- **调试台增强**：`/retrieve` 页面的 chunk 卡片显示「所属章节」和「块类型」
- **保留 .txt 回退**：纯文本文件仍走接近旧行为的分块方式，不阻塞

## Capabilities

### New Capabilities

- `structured-chunking`: 结构化 Markdown 切块能力 — 沿标题边界分节、表格整块保留表头、每 chunk 携带 `heading_path` 和 `chunk_type` 元数据
- `batch-reindex`: 批量重建索引能力 — 脚本对指定知识库下所有已索引文档跑 purge + 重新索引，打印进度和统计

### Modified Capabilities

- `retrieve-api`: 检索响应中 chunk 的 metadata 新增 `heading_path` 和 `chunk_type` 字段，前端调试台据此展示章节和块类型信息

## Impact

| 维度 | 影响 |
|------|------|
| 代码 | `src/ragnexus/domain/chunking.py` 重构，`indexing_service.py` chunker 调用签名变更，`document_reindex_uc.py` 状态检查放宽，`di.py` chunker 注入切换 |
| 依赖 | 新增 `structchunk` 库（已存在于 `.tmp/structchunk_audit/`，需集成到项目） |
| API | `POST /documents/{id}/reindex` 行为变更（**BREAKING**: 现在 SUCCESS 文档也可调用），`POST /v1/rag:retrieve` 响应 metadata 新增字段（向下兼容） |
| 数据库 | chunks.metadata JSONB 新增 `heading_path`、`chunk_type`、`table_part` 字段，已有数据需 reindex 后更新 |
| 前端 | `admin/src/pages/retrieve.tsx` chunk 卡片展示逻辑变更 |
```

## openspec/changes/structured-markdown-chunking/design.md

- Source: openspec/changes/structured-markdown-chunking/design.md
- Lines: 1-157
- SHA256: 0dfba522da2060b27bcca9150f16619c9d4517347852e61284daf3a900a864f5

[TRUNCATED]

```md
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
- 将 structchunk 的核心包（`src/structchunk/`）拷贝到 `src/ragnexus/infra/structchunk/` 或作为 pip 可安装包
- `di.py` 中将 `chunker=heading_aware_split` 替换为 `chunker=chunk_markdown`
- 新增薄封装函数 `chunk_markdown(content: str, max_chars: int, ...) -> list[dict]` 适配现有 `IndexingService` 的 chunker 签名

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
```

Full source: openspec/changes/structured-markdown-chunking/design.md

## openspec/changes/structured-markdown-chunking/tasks.md

- Source: openspec/changes/structured-markdown-chunking/tasks.md
- Lines: 1-42
- SHA256: b78e692c2a4997905cd4cd6eb72d2ef62ffc8de522da3dffa4035f54904c56b1

```md
# Tasks: 结构化 Markdown 切块

## 1. structchunk 集成

- [ ] 1.1 将 `.tmp/structchunk_audit/src/structchunk/` 拷贝到 `src/ragnexus/infra/structchunk/`，验证其单测通过
- [ ] 1.2 新建 `src/ragnexus/infra/__init__.py` 和 `src/ragnexus/infra/structchunk_bridge.py`，封装 `chunk_markdown(content, max_chars, **kwargs) -> list[dict]`
- [ ] 1.3 `chunk_markdown` 实现 metadata 映射逻辑：`header_breadcrumb` → `heading_path`，`source_element_type` → `chunk_type`，保留 `heading`/`heading_level` 向后兼容
- [ ] 1.4 配置新增变量 `TABLE_MAX_ROWS_PER_CHUNK`（默认 10）到 `Settings` 和 `.env`

## 2. 切块器替换

- [ ] 2.1 `src/ragnexus/domain/chunking.py`：保留 `fixed_size_split`，`heading_aware_split` 标记废弃
- [ ] 2.2 `src/ragnexus/application/indexing_service.py`：按扩展名分流（.md → structchunk，.txt → fixed_size_split），metadata 构建含 `heading_path`/`chunk_type`
- [ ] 2.3 `src/ragnexus/di.py`：chunker 依赖注入从 `heading_aware_split` 切换到 `chunk_markdown`，max_chars 参数对齐

## 3. 单文档 reindex 扩展

- [ ] 3.1 `src/ragnexus/application/document_reindex_uc.py`：状态检查从 `!= FAILED` 改为 `== PROCESSING` 拒绝，允许 SUCCESS 状态
- [ ] 3.2 `src/ragnexus/adapters/http/document_router.py`：扩展 `POST /documents/{id}/reindex` 的接口描述和响应说明

## 4. 批量 reindex 脚本

- [ ] 4.1 新建 `scripts/reindex_knowledge_base.py`：支持 `--kb-id`（必填）、`--tenant-id`（可选）、`--document-id`（可多次传入）
- [ ] 4.2 脚本实现 purge + PROCESSING 置状态 + Celery task 提交，按文档逐条执行
- [ ] 4.3 单篇失败不阻断其余文档，结束时打印 success/failed/skipped 三项统计

## 5. 调试台展示

- [ ] 5.1 `admin/src/pages/retrieve.tsx`：chunk 卡片 content 折叠区上方新增「所属章节」和「块类型」展示行
- [ ] 5.2 仅在 `heading_path` 或 `chunk_type` 有值时显示，无值时不影响现有布局

## 6. 测试

- [ ] 6.1 `tests/unit/infra/test_structchunk_bridge.py`：测试 metadata 映射（heading_path 格式、chunk_type 映射、向后兼容字段）
- [ ] 6.2 `tests/unit/application/test_indexing_service.py`：更新 chunker mock，验证 .md 走 structchunk、.txt 走 fixed_size_split
- [ ] 6.3 `tests/unit/application/test_document_reindex_uc.py`：SUCCESS 文档可 reindex，PROCESSING 文档拒绝
- [ ] 6.4 `tests/unit/domain/test_chunking.py`：fixed_size_split 行为不变，heading_aware_split 弃用标记验证

## 7. 文档

- [ ] 7.1 `README.md` 新增「切块策略升级后 reindex」小节，说明脚本用法和执行时机
- [ ] 7.2 `AGENTS.md` 补充结构化切块相关诊断信息（chunk_type 查询、reindex 常见问题）
```

## openspec/changes/structured-markdown-chunking/specs/batch-reindex/spec.md

- Source: openspec/changes/structured-markdown-chunking/specs/batch-reindex/spec.md
- Lines: 1-76
- SHA256: bde1ed70b1a568661069b292e3552fc49c5a2007c8c8fc05fc80d4ac562b7af4

```md
# batch-reindex Specification

## ADDED Requirements

### Requirement: 批量知识库重建索引

系统 SHALL 提供 `scripts/reindex_knowledge_base.py` 脚本，接受 `--kb-id`（必填）、可选的 `--tenant-id` 和可多次传入的 `--document-id` 参数，对指定知识库下所有 `status=SUCCESS` 的文档（或 `--document-id` 指定的文档）执行重建索引。

脚本内部 SHALL 按以下流程处理每篇文档：

1. 清除该文档在 pgvector 和 Elasticsearch 中的旧 chunk
2. 将文档状态置为 `PROCESSING`
3. 提交 Celery `index_document_task` 异步任务

脚本执行中 SHALL 打印每篇文档的进度（正在处理/完成/失败），单篇失败时记录 `document_id`，不阻断其余文档继续执行。脚本结束时 SHALL 打印 `success`、`failed`、`skipped` 三项统计数字。

`PROCESSING` 中的文档 SHALL 被拒绝重复 reindex，统计进 `skipped`。

#### Scenario: 对整个知识库执行 reindex

- **GIVEN** 知识库 `kb_ecom` 下有 8 篇 `status=SUCCESS` 的文档
- **WHEN** 运行 `python scripts/reindex_knowledge_base.py --kb-id kb_ecom`
- **THEN** 8 篇文档依次被清除旧 chunk 并提交 Celery 任务
- **AND** 脚本结束时输出 `已完成：8 篇  失败：0 篇  跳过：0 篇`
- **AND** Worker 完成后，各文档 `chunks.metadata` 含 `heading_path` 和 `chunk_type`

#### Scenario: 指定文档 reindex

- **GIVEN** 知识库 `kb_ecom` 下有 8 篇文档
- **WHEN** 运行 `python scripts/reindex_knowledge_base.py --kb-id kb_ecom --document-id doc_aaa --document-id doc_bbb`
- **THEN** 仅 `doc_aaa` 和 `doc_bbb` 被 reindex
- **AND** 其余 6 篇文档不受影响

#### Scenario: 不存在的知识库

- **GIVEN** `--kb-id` 指向不存在的知识库
- **WHEN** 运行脚本
- **THEN** 脚本输出友好错误信息（如 `知识库 kb_xxx 不存在`）
- **AND** 脚本以非零退出码退出，不崩溃

#### Scenario: 某篇文档 Worker 索引失败

- **GIVEN** 知识库下有 5 篇文档，其中第 3 篇的 embedding API 临时不可用
- **WHEN** 运行脚本，Worker 在第 3 篇时失败
- **THEN** 脚本记录 `doc_id`，其余文档继续执行
- **AND** 结束时输出类似 `已完成：4 篇  失败：1 篇  跳过：0 篇`

#### Scenario: PROCESSING 中的文档被跳过

- **GIVEN** 知识库下有 1 篇 `status=PROCESSING` 的文档
- **WHEN** 运行脚本
- **THEN** 该文档不触发重复 reindex
- **AND** 统计进 `skipped`

### Requirement: 单文档强制 reindex

`POST /v1/documents/{doc_id}/reindex` API SHALL 允许 `status=SUCCESS` 的文档接受重建索引，不再限制仅 `FAILED` 状态。

`PROCESSING` 中的文档 SHALL 仍被拒绝，返回 `RESOURCE_CONFLICT` 错误。

重建流程 SHALL 与 FAILED 重试共用同一套 purge → PROCESSING → Celery task 逻辑。

#### Scenario: SUCCESS 文档可强制重建

- **GIVEN** 一篇 `status=SUCCESS` 的文档
- **WHEN** 调用 `POST /v1/documents/{doc_id}/reindex`
- **THEN** 旧 chunk 被清除，文档状态变为 `PROCESSING`
- **AND** Celery Worker 用新版 chunker 重新索引
- **AND** Worker 完成后，文档状态恢复 `SUCCESS`

#### Scenario: PROCESSING 文档拒绝重入

- **GIVEN** 一篇 `status=PROCESSING` 的文档
- **WHEN** 调用 `POST /v1/documents/{doc_id}/reindex` 或运行 reindex 脚本
- **THEN** API 返回 `RESOURCE_CONFLICT` 错误
- **AND** 脚本将其计入 `skipped`
```

## openspec/changes/structured-markdown-chunking/specs/retrieve-api/spec.md

- Source: openspec/changes/structured-markdown-chunking/specs/retrieve-api/spec.md
- Lines: 1-55
- SHA256: 9dfbb9e093b918f6b2f80c71c965568fddbcb0757da85911a4c40313bac625b6

```md
# retrieve-api Specification (Delta)

## MODIFIED Requirements

### Requirement: 检索响应 chunk metadata 包含结构化切块信息

`POST /v1/rag:retrieve` 响应的 `hits[].metadata` SHALL 新增以下字段（来自 chunk 的 metadata）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `heading_path` | `str` | 标题层级路径，纯文本为空字符串 |
| `chunk_type` | `str` | `section` / `table` / `code` / `list` / `text` |

新增字段 SHALL 向下兼容：使用旧切块器索引的文档，这两个字段为 `null` 或空值。

`_serialize_hit()` SHALL 保留原有行为，新字段随 `h.metadata` 自动透传，无需 JSON 序列化层改动。

#### Scenario: 结构化切块的文档检索

- **GIVEN** 一篇已用结构化切块索引的文档，chunk metadata 含 `heading_path: "平台交易规则 / 退款时效"` 和 `chunk_type: "section"`
- **WHEN** 调用 `POST /v1/rag:retrieve` 检索到该 chunk
- **THEN** 响应 `hits[].metadata.heading_path` 为 `"平台交易规则 / 退款时效"`
- **AND** `hits[].metadata.chunk_type` 为 `"section"`

#### Scenario: 旧切块器索引的文档兼容

- **GIVEN** 一篇用旧切块器索引的文档，chunk metadata 不含 `heading_path` 和 `chunk_type`
- **WHEN** 调用 `POST /v1/rag:retrieve` 检索到该 chunk
- **THEN** 响应不报错
- **AND** `hits[].metadata.heading_path` 为 `null` 或空
- **AND** `hits[].metadata.chunk_type` 为 `null` 或空

#### Scenario: 表格 chunk 检索

- **GIVEN** 一篇含表格的文档，表格 chunk metadata 含 `chunk_type: "table"` 和 `heading_path: "平台交易规则 / 叠加规则"`
- **WHEN** 检索 "满减和优惠券能否叠加"
- **THEN** Top chunk 的 `chunk_type` 为 `"table"`
- **AND** `heading_path` 含正确的章节路径
- **AND** content 含完整表头行

### Requirement: 调试台展示 chunk 元信息

检索调试台页面 `/retrieve` 的 chunk 卡片 SHALL 在 content 折叠区上方展示 `heading_path` 和 `chunk_type`（当两者有值时）。

#### Scenario: 调试台展示章节和类型

- **GIVEN** 检索结果包含一个 `heading_path: "测试知识库 / 第一节"`、`chunk_type: "section"` 的 chunk
- **WHEN** 用户在调试台查看检索结果
- **THEN** 该 chunk 卡片上展示 `所属章节：测试知识库 / 第一节` 和 `块类型：section`

#### Scenario: 无章节信息的 chunk

- **GIVEN** 检索结果包含一个 `heading_path` 为空且无 `chunk_type` 的 chunk（如纯文本文档）
- **WHEN** 用户在调试台查看检索结果
- **THEN** 该 chunk 卡片不展示章节和块类型行，其他信息正常显示
```

## openspec/changes/structured-markdown-chunking/specs/structured-chunking/spec.md

- Source: openspec/changes/structured-markdown-chunking/specs/structured-chunking/spec.md
- Lines: 1-97
- SHA256: 73465fc7bf45d5bc92ff01c9d0be7232aaf88ffa22bb5b8946cbeb0d888eb132

[TRUNCATED]

```md
# structured-chunking Specification

## ADDED Requirements

### Requirement: Markdown 文档按标题层级结构化切块

系统 SHALL 在上传 `.md` 文档时，按 `#` / `##` 标题边界分节切块，不在标题行中间截断，不在小节中间截断。

`###` 及更深层级标题的内容 SHALL 归入其所属的最近 `##` 或 `#` 节的 chunk 中，不单独成块。

#### Scenario: 含二级标题的文档正确分节

- **GIVEN** 一篇 Markdown 文档含 `# 测试知识库`、`## 第一节` 及其内容、`## 第二节` 及其内容
- **WHEN** 系统对该文档执行索引
- **THEN** 至少生成 2 个 chunk，分别对应「第一节」和「第二节」
- **AND** chunk 不在 `## 第` 这样的标题行中间截断
- **AND**「第一节」的 chunk 的 `heading_path` 为 `"测试知识库 / 第一节"`
- **AND**「第二节」的 chunk 的 `heading_path` 为 `"测试知识库 / 第二节"`

#### Scenario: 三级标题归入上级节

- **GIVEN** 文档「第一节」下含 `### 1.1 子内容` 段落
- **WHEN** 系统对该文档执行索引
- **THEN** `### 1.1 子内容` 下的段落出现在「第一节」的 chunk 中
- **AND** 不存在仅含三级标题内容的独立 chunk

#### Scenario: 无标题文档回退

- **GIVEN** 一篇不含 `#` 或 `##` 的 `.md` 文档
- **WHEN** 系统对该文档执行索引
- **THEN** 整篇视为一节，按段落优先或字符窗口切块
- **AND** 行为接近旧 `fixed_size_split` 效果

### Requirement: 表格识别与专项切块

系统 SHALL 识别 Markdown 表格（`| ... |` 行）并将其作为独立 chunk 类型处理。

**小表**（整表字符数不超过 `CHUNK_MAX_CHARS`）SHALL 作为一个完整 chunk，`chunk_type` 为 `table`，content 含完整表头和全部数据行。

**大表**（超过 `CHUNK_MAX_CHARS`）SHALL 保留表头，按每组最多 `TABLE_MAX_ROWS_PER_CHUNK` 条数据行分组成多个 chunk，每个 chunk 的 content 顶部重复表头行，`table_part` 字段从 1 开始递增。

表格与前后段落 SHALL 分开成块，不强行拼合。

#### Scenario: 小表整块存储

- **GIVEN** 一篇 Markdown 文档含一个 3 行数据的小表格
- **WHEN** 系统对该文档执行索引
- **THEN** 该表格作为一个完整 chunk，`chunk_type` 为 `table`
- **AND** content 含完整表头行和全部 3 行数据
- **AND** 不存在表格数据行被截断为半行的 chunk

#### Scenario: 大表分组存储含表头

- **GIVEN** 一篇 Markdown 文档含一个 25 行数据的大表格
- **WHEN** 系统对该文档执行索引，`TABLE_MAX_ROWS_PER_CHUNK` 为 10
- **THEN** 表格被分为 3 个 chunk
- **AND** 每个 chunk 的 content 顶部重复表头行
- **AND** `table_part` 字段从 1 递增到 3
- **AND** 每个 chunk 的 content 不超过 `CHUNK_MAX_CHARS`

### Requirement: chunk metadata 增强

系统 SHALL 为每个 chunk 的 metadata 新增以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `heading_path` | `str` | 标题层级路径，格式 `一级标题 / 二级标题`，纯文本文档为空字符串 |
| `chunk_type` | `str` | 块类型：`section`、`table`、`code`、`list`，纯文本为 `text` |
| `table_part` | `int` | 大表分组序号，仅表格 chunk 有值，从 1 开始 |

同时 SHALL 保留 `heading` 和 `heading_level` 字段以向后兼容。

#### Scenario: heading_path 格式正确

- **GIVEN** chunk 所属节的标题栈为 `["# 平台交易规则", "## 退款时效"]`
- **WHEN** chunk metadata 写入 `heading_path`
- **THEN** `heading_path` 值为 `"平台交易规则 / 退款时效"`
- **AND** 不含 markdown 标记符 `#`

#### Scenario: 纯文本文档 metadata
```

Full source: openspec/changes/structured-markdown-chunking/specs/structured-chunking/spec.md

