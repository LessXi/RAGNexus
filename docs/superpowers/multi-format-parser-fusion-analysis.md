# 多格式文档解析 — 需求融合分析

> 基于三篇飞书需求文档 + RAGNexus 项目现状，从第一性原理出发的融合分析。

## 一、需求摘要

三篇文档（需求背景、实现提示词、测试验收）描述的核心需求：

1. **新增 .docx / .pdf 格式支持**：业务方直接上传原始文件，由系统自动解析
2. **解析层设计**：插件化的 DocumentParser，Word→mammoth，PDF→PyMuPDF，输出 Markdown 风格字符串
3. **上传双模式**：保持现有 JSON 文本上传不变，新增 multipart 二进制上传
4. **原文件存储**：保存原始二进制文件，支持 reparse
5. **数据库扩展**：新增 `source_file_path`、`source_filename`、`source_type` 字段
6. **前端改造**：上传页支持 .pdf/.docx，列表页展示格式 badge

## 二、RAGNexus 现状对标

### 2.1 已有基础（可直接复用）

| 现状 | 对齐度 | 说明 |
|------|--------|------|
| `adapters/parsers/` 目录 | ✅ 完全对齐 | 已有 parser 适配器层，`MarkdownAndTextParser` 实现 `ParserPort` |
| `ParserPort` 协议 | ✅ 完全对齐 | `async def parse(content: bytes, filename: str) -> ParsedDocument` |
| `ParsedDocument` 模型 | ⚠️ 部分对齐 | 当前为 `sections` + `raw_text` 结构，需求是 `content` + `source_type` + `metadata` |
| `IndexingService` 流水线 | ✅ 完全对齐 | parse→chunk→embed→双写 流程，新 parser 可直接插入 |
| Celery 异步任务 | ✅ 完全对齐 | `index_document_task` 已有重试、超时监控 |
| ES + pgvector 双写 | ✅ 完全对齐 | 事务协调语义已完善，无需改动 |
| 前端上传组件 | ⚠️ 部分对齐 | 上传、轮询、队列已有，但仅 .md/.txt |
| 租户/配额系统 | ✅ 完全对齐 | 限流、配额检查已完善 |

### 2.2 核心差异（需要适配）

| 差异点 | 需求文档 (rag-center) | RAGNexus 现状 | 融合策略 |
|--------|----------------------|---------------|----------|
| **Parser 输出模型** | `ParsedDocument(content, source_type, metadata)` — 扁平的 Markdown 字符串 | `ParsedDocument(filename, sections, raw_text)` — 结构化章节列表 | **扩展**现有模型，保持 sections 结构 |
| **Parser 注册机制** | `registry.py` + `get_document_parser(filename)` | 直接实例化 `MarkdownAndTextParser()` | **新增** registry 适配器 |
| **解析时机** | Worker 中从原文件读取→解析→写入 content | 上传时 UTF-8 解码→存入 content | **分离**：二进制文件延迟解析 |
| **原文件存储** | `DOCUMENT_STORAGE_PATH/{tenant_id}/{doc_id}/{filename}` | 无存储，解码后丢弃原文件 | **新增** file storage 适配器 |
| **Chunker 输入** | Markdown 字符串 → splitter 按标题切分 | `ParsedDocument.sections` → heading_aware_split | **保持** sections 输入，新 parser 也输出 sections |
| **Upload API** | JSON + multipart 双模式 | 仅 multipart | **新增** JSON 文本上传路由 |

## 三、第一性原理分析

### 3.1 核心问题

> **如何以最小改动让 RAGNexus 接受 Word/PDF 原始文件，同时不破坏现有 Markdown/文本链路？**

### 3.2 关键设计决策

#### 决策 1：Parser 输出模型 — 扩展而非替换

**需求文档的做法**：Parser 输出扁平 Markdown 字符串 → splitter 消费。

**RAGNexus 的做法**：Parser 输出 `ParsedDocument(sections=...)` → chunker 消费。

**融合决策**：**保持 sections 模型，扩展 ParsedDocument 而非替换**。

理由（第一性原理）：
- RAGNexus 的 `heading_aware_split` 已经能正确处理标题、表格（通过 sections 结构），这是**已验证的能力**
- 改为扁平 Markdown 字符串需要重写 splitter，**增加了风险和改动面**，收益不明确
- 新 Parser（Word/PDF）只需把解析结果**转换为 sections 结构**，比输出 Markdown 字符串更精确
- 扩展 `ParsedDocument` 增加 `source_type` 和 `metadata` 字段即可，向下兼容

**具体做法**：
```python
@dataclass
class ParsedDocument:
    filename: str
    sections: list[Section]
    raw_text: str
    source_type: str = "text"     # 新增: text | markdown | docx | pdf
    metadata: dict = field(default_factory=dict)  # 新增: parser_name, page_count, warnings
```

#### 决策 2：Parser 注册机制 — 在现有 adapters/parsers 下新增 registry

**需求文档的做法**：`app/providers/parsers/registry.py` + `get_document_parser(filename)`。

**融合决策**：在现有 `adapters/parsers/` 目录下新增 `registry.py`。

**具体做法**：
```
src/ragnexus/adapters/parsers/
  __init__.py          # 导出 get_parser()
  registry.py          # 按扩展名注册/选择 parser
  md_and_txt.py        # 现有，改名 MarkdownParser
  docx.py              # 新增 mammoth Word parser
  pdf.py               # 新增 PyMuPDF PDF parser
```

#### 决策 3：解析时机 — 上传时轻量校验 + Worker 中延迟解析

**需求文档的做法**：上传时存原文件，Worker 中 prepare_document_content → parse → 写入 content。

**融合决策**：**采纳需求文档的设计**。

理由（第一性原理）：
- Word/PDF 解析是 **CPU 密集型操作**（mammoth 转换、PDF 按页抽取），不应阻塞 HTTP 响应
- 上传时只做**文件格式校验**（扩展名白名单）和**文件大小校验**，快速返回
- 原文件存到磁盘，Worker 中异步解析，**与现有架构一致**

**具体做法**：
- JSON 文本上传：行为完全不变，content 直接存入
- multipart 二进制上传：保存原始文件到 `DOCUMENT_STORAGE_PATH`，content 先置空，`source_type` 标记为 docx/pdf
- Worker 中：`IndexingService` 增加文件读取步骤 → Parser 解析 → 存入 content → 现有流程

#### 决策 4：Upload 双模式 — 同一路径，不同 Content-Type

**需求文档的做法**：`POST /api/v1/documents/upload` 同时支持 JSON 和 multipart。

**融合决策**：**采纳，但 JSON 模式需新增路由**。

理由：
- RAGNexus 的 upload 路由**只有 multipart**（`Form + UploadFile`），不支持 JSON body
- 需求要求 JSON 上传保持零破坏，这意味着需要一个**独立的 JSON 路由**或**同一路由的条件分发**

**具体做法**：
- 新建 `POST /v1/documents/upload-text`（JSON body：`{kb_id, title, content}`）
- 或：在现有路由中根据 `Content-Type` header 分发（FastAPI 原生支持多 Content-Type 困难）
- **推荐方案**：新增独立路由，路径 `/v1/documents:upload-text`，与 multipart 路由 `/v1/documents:upload` 对称

#### 决策 5：文件存储 — 新增 FileStoragePort 适配器

**需求文档的做法**：`DOCUMENT_STORAGE_PATH/{tenant_id}/{document_id}/{filename}`。

**融合决策**：**采纳，独立为适配器**。

**具体做法**：
```
src/ragnexus/adapters/file_storage/
  __init__.py
  local.py    # LocalFileStorage — 本地文件系统存储
```

- 接口：`save(tenant_id, doc_id, filename, content: bytes) -> str`（返回存储路径）
- 接口：`read(path: str) -> bytes`
- 接口：`delete(path: str) -> None`
- 配置：`DOCUMENT_STORAGE_PATH`、`DOCUMENT_MAX_SIZE_MB`

## 四、变更范围清单

### 4.1 领域模型 (domain/)

| 文件 | 变更 | 说明 |
|------|------|------|
| `domain/models.py` | **扩展** ParsedDocument | +source_type, +metadata |
| `domain/models.py` | **扩展** Document | +source_file_path, +source_filename |
| `domain/ports.py` | **扩展** ParserPort | parse() 签名不变，输出模型扩展 |
| `domain/ports.py` | **新增** FileStoragePort | save/read/delete |

### 4.2 适配器 (adapters/)

| 文件 | 变更 | 说明 |
|------|------|------|
| `adapters/parsers/registry.py` | **新增** | 按扩展名选择 parser |
| `adapters/parsers/md_and_txt.py` | **微调** | 输出增加 source_type="markdown" |
| `adapters/parsers/docx.py` | **新增** | mammoth Word 解析 |
| `adapters/parsers/pdf.py` | **新增** | PyMuPDF PDF 解析 |
| `adapters/file_storage/local.py` | **新增** | 本地文件存储 |
| `adapters/document/pg.py` | **扩展** | create 支持新字段，get 查询新字段 |
| `adapters/http/upload_doc_router.py` | **扩展** | 支持二进制模式（暂存文件） |

### 4.3 应用层 (application/)

| 文件 | 变更 | 说明 |
|------|------|------|
| `application/upload_doc_use_case.py` | **扩展** | 双模式：文本直存 vs 文件暂存 |
| `application/indexing_service.py` | **扩展** | 增加 prepare_document_content 步骤 |
| `application/document_reindex_uc.py` | **扩展** | reparse=true 支持 |

### 4.4 配置 (config.py)

| 变更 | 说明 |
|------|------|
| + `DOCUMENT_STORAGE_PATH` | 默认 `./data/uploads` |
| + `DOCUMENT_MAX_SIZE_MB` | 升级为 MB 单位，默认 20 |
| 扩展 `max_file_size` | 保持向后兼容 |

### 4.5 数据库

| 变更 | 说明 |
|------|------|
| ALTER TABLE documents ADD `source_file_path` TEXT | 原文件存储路径，可空 |
| ALTER TABLE documents ADD `source_filename` TEXT | 原始文件名 |
| ALTER TABLE documents ADD `source_type` TEXT DEFAULT 'text' | 格式来源 |

### 4.6 错误码

| 变更 | 说明 |
|------|------|
| + `DOCUMENT_PARSE_FAILED = 20023` | 解析失败，HTTP 422 |

### 4.7 前端

| 文件 | 变更 | 说明 |
|------|------|------|
| `utils/file-filter.ts` | **扩展** | 增加 .pdf, .docx |
| `services/api.ts` | **新增** | `uploadDocJson()` JSON 上传 |
| `pages/upload-doc.tsx` | **扩展** | 双模式上传 |
| `components/StatusBadge.tsx` | **扩展** | 格式 badge（可选） |

### 4.8 依赖

| 变更 | 说明 |
|------|------|
| `pyproject.toml` [parsers] | mammoth>=1.6.0, pymupdf>=1.24.0 |
| Dockerfile | 安装 parsers extra |

### 4.9 不受影响的模块（零改动）

- ✅ `domain/chunking.py` — heading_aware_split 不变
- ✅ `adapters/vector_store/` — pgvector 不变
- ✅ `adapters/keyword_search/` — ES 不变
- ✅ `adapters/embedder/` — embedding 不变
- ✅ `application/retrieve_use_case.py` — 检索不变
- ✅ `application/kb_*` — 知识库管理不变
- ✅ `services/quota_service.py` — 配额不变
- ✅ `services/rate_limit_service.py` — 限流不变
- ✅ `tenant/` — 套餐系统不变
- ✅ `observability/` — Langfuse 不变
- ✅ 检索页、列表页（除可选 badge）

## 五、风险与注意事项

### 5.1 架构风险

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| `ParsedDocument` 模型扩展影响所有 parser 消费者 | 中 | 新字段有默认值，向下兼容；chunker 不读新字段 |
| Word/PDF 解析 CPU 密集影响 Worker 性能 | 低 | 已有 Celery 异步 + 并发控制 |
| 大 PDF 解析超时 | 中 | 设置合理的 task soft/hard time limit |

### 5.2 与需求文档的差异及理由

| 差异 | 需求文档做法 | RAGNexus 做法 | 理由 |
|------|-------------|---------------|------|
| ParsedDocument 模型 | 扁平 Markdown 字符串 | sections 结构 + raw_text | sections 已被 splitter 验证有效，改为字符串需要重写 splitter |
| Parser 输入格式 | `file_bytes` | `file_bytes` | 一致 |
| 解析入口 | `prepare_document_content()` 独立函数 | IndexingService 内嵌 | 复用现有 DI 和生命周期管理 |
| 错误处理 | 独立 `DOCUMENT_PARSE_FAILED` | 放入现有 FAILED 状态 + error_message | 兼容现有前端轮询逻辑 |
| 验证脚本 | `verify_parser_12.py` | `scripts/verify_multi_format.py` | 命名对齐项目约定 |

### 5.3 实现顺序建议

```
Phase 1: 领域模型 + 错误码 (1 天)
  → ParsedDocument 扩展, Document 扩展, DOCUMENT_PARSE_FAILED 错误码

Phase 2: Parser 插件层 (2 天)
  → registry + DocxParser + PdfParser + MarkdownParser 微调

Phase 3: 文件存储 + 数据库迁移 (1 天)
  → FileStoragePort + LocalFileStorage + Migration

Phase 4: Upload 双模式 + 索引编排 (2 天)
  → JSON upload 路由 + 二进制暂存 + prepare_document_content

Phase 5: 前端 + 验收 (1 天)
  → file-filter 扩展 + 上传页改造 + 验证脚本

总计: ~7 天
```

## 六、结论

RAGNexus 的现有架构与多格式文档解析需求**高度对齐**：
- `adapters/parsers/` 层已存在，只需扩展而非新建
- `IndexingService` 的 parse→chunk→embed→write 流程可直接复用
- Celery 异步任务 + 超时监控已完善
- 租户/配额/限流系统零改动
- 前端上传组件只需扩展文件类型过滤

核心差异仅在于 **ParsedDocument 模型选择 sections 而非扁平字符串**，这是基于第一性原理的权衡：保持已验证的 splitter 能力，避免引入不必要的回归风险。新 Parser（Word/PDF）只需将解析结果填充为 sections 结构即可无缝接入。
