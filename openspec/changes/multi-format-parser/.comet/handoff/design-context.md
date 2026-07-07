# Comet Design Handoff

- Change: multi-format-parser
- Phase: design
- Mode: compact
- Context hash: 4a4914235c9dde0cb2770566024268dc60a3671be66128c96385229e6914ebbe

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/multi-format-parser/proposal.md

- Source: openspec/changes/multi-format-parser/proposal.md
- Lines: 1-40
- SHA256: 88fef37504db88cb624c76f1419851392b818b32b3cf8c69ccbe8628c559f742

```md
## Why

当前 RAGNexus 仅接受 `.md` 和 `.txt` 纯文本文件上传。真实业务场景中，接入中台的业务方持有大量 Word 制度文件、HR 手册、PDF 合同等二进制格式文档。要求业务方自行将 Word/PDF 转换为纯文本后再上传，将解析成本推回每个接入方，阻碍了"文档入库"能力的完整性。

本次变更在现有切块流水线之前增加一层插件化文档解析层，使 RAGNexus 可直接接收 `.docx` 和 `.pdf` 原始文件，自动解析后进入现有索引和检索流程。

## What Changes

- **新增** 插件化 Parser 注册机制（`adapters/parsers/registry.py`），按文件扩展名选择解析器
- **新增** Word 解析器 `DocxParser`（基于 mammoth），将 `.docx` 转为结构化章节
- **新增** PDF 解析器 `PdfParser`（基于 PyMuPDF），抽取文字并按页分节
- **扩展** `ParsedDocument` 领域模型，增加 `source_type` 和 `metadata` 字段
- **新增** 文件存储适配器 `LocalFileStorage`，保存上传的原始二进制文件
- **扩展** Upload API 支持 JSON 文本上传（`/v1/documents:upload-text`），与现有 multipart 上传并存
- **扩展** multipart 上传支持二进制格式（`.docx`/`.pdf`），原文件暂存磁盘，Worker 中延迟解析
- **扩展** Document 模型和数据库表，增加 `source_file_path`、`source_filename`、`source_type` 字段
- **新增** `reparse=true` 重索引参数，支持从原始文件重新解析
- **扩展** 前端上传页支持 `.pdf`/`.docx` 文件选择
- **新增** 错误码 `DOCUMENT_PARSE_FAILED`（20023）

## Capabilities

### New Capabilities

- `multi-format-parsing`: 插件化文档解析能力，支持 Word（.docx）和 PDF 文件自动解析为结构化文本，输出统一的 `ParsedDocument` 供现有切块和索引流水线消费。包含 Parser 注册机制、原文件存储、reparse 支持和前端格式扩展。

### Modified Capabilities

<!-- 本次不修改任何已有 spec 的需求级行为，纯新增能力 -->

## Impact

- **领域模型**: `ParsedDocument` 增加 `source_type`/`metadata`；`Document` 增加 `source_file_path`/`source_filename`
- **适配器**: 新增 `adapters/parsers/` 下 docx/pdf/registry；新增 `adapters/file_storage/local.py`
- **应用层**: `UploadDocumentUseCase` 支持双模式；`IndexingService` 增加文件读取步骤
- **数据库**: `documents` 表新增 3 列（migration）
- **API**: 新增 `POST /v1/documents:upload-text`；扩展 reindex 支持 `reparse` 参数
- **前端**: `file-filter.ts` 扩展格式；`upload-doc.tsx` 适配双模式
- **依赖**: 新增 `mammoth>=1.6.0`、`pymupdf>=1.24.0` 可选依赖组 `[parsers]`
- **不受影响**: 切块、embedding、ES/pgvector、检索、知识库管理、租户、配额、限流
```

## openspec/changes/multi-format-parser/design.md

- Source: openspec/changes/multi-format-parser/design.md
- Lines: 1-160
- SHA256: 484b55c345d8b5a25d5f9f556b162c5a141d8f350a165c382d424ef739c7c0eb

[TRUNCATED]

```md
## Context

RAGNexus 采用 Clean Architecture 分层：`domain`（ports + models）→ `application`（use cases + indexing service）→ `adapters`（parsers, http, vector_store, keyword_search 等）→ `composition`（DI 组装）。

当前文档处理链路：`multipart upload → UTF-8 decode → Document(content=text) → Celery task → IndexingService.execute()`，其中 IndexingService 内 `ParserPort.parse()` → `heading_aware_split()` → embed → ES + pgvector 双写。

`adapters/parsers/` 目录已存在，包含 `MarkdownAndTextParser`（实现 `ParserPort`）。`ParsedDocument` 输出 `sections: list[Section]` + `raw_text`，供 `heading_aware_split` 按标题分块。

本次变更在该目录下新增 Word 和 PDF 解析器，并扩展上传和索引编排以支持二进制文件。

## Goals / Non-Goals

**Goals:**
- 使 RAGNexus 直接接收 `.docx` 和 `.pdf` 文件，自动解析后进入现有索引流水线
- 保持现有 `.md`/`.txt` 上传行为零破坏
- Parser 架构可插拔，后续新增格式只需写新 Parser 并注册
- 支持从原始文件重新解析（reparse）
- 上传接口同时支持 JSON 文本和 multipart 二进制两种模式

**Non-Goals:**
- OCR 扫描件 PDF 识别
- 旧版 `.doc` 格式支持
- HTML、Excel、PPT 等格式
- 修改切块（chunking）、embedding、向量存储、关键词检索、retrieve 逻辑
- 修改知识库管理、租户系统、配额/限流系统

## Decisions

### 决策 1：Parser 输出保持 sections 模型，扩展而非替换

**选型**：保持 `ParsedDocument(sections=..., raw_text=...)` 结构，增加 `source_type` 和 `metadata` 字段。

**替代方案**：改为扁平 Markdown 字符串输出（需求文档建议方案）。

**理由**：
- RAGNexus 的 `heading_aware_split` 已基于 sections 结构验证有效，改为扁平字符串需重写 splitter，引入不必要的回归风险
- sections 结构比 Markdown 字符串更精确：标题层级、表格结构等信息不会因 Markdown 序列化/反序列化丢失
- Word/PDF Parser 只需将解析结果转换为 sections 即可无缝接入，实现成本更低
- `source_type` 和 `metadata` 字段向后兼容（有默认值），不影响现有 consumer

**ParsedDocument 扩展后结构**：
```python
@dataclass
class ParsedDocument:
    filename: str
    sections: list[Section]
    raw_text: str
    source_type: str = "text"        # 新增: text | markdown | docx | pdf
    metadata: dict = field(default_factory=dict)  # 新增: parser_name, page_count, warnings
```

### 决策 2：Parser 注册机制 — 在现有 adapters/parsers 下新增 registry

**选型**：在 `adapters/parsers/registry.py` 实现按扩展名选择 Parser。

**替代方案**：在 DI 层（composition.py）硬编码条件分支。

**理由**：
- 与项目已有的 Provider 模式一致（embedder、llm、rerank 均有 adapter 注册）
- 新增格式只需：写一个 Parser 类 + `registry.register(ext, parser)`，零侵入
- Registry 返回 ParserPort 协议，调用方无感知

**Registry 接口**：
```python
# adapters/parsers/registry.py
_parsers: dict[str, ParserPort] = {}

def register(ext: str, parser: ParserPort) -> None: ...
def get_parser(filename: str) -> ParserPort:  # 按扩展名匹配，未匹配抛 UNSUPPORTED_FORMAT
```

### 决策 3：上传双模式 — 同一路径，按 Content-Type 分发

**选型**：新增 `POST /v1/documents:upload-text`（JSON body），原有 `POST /v1/documents:upload` 扩展支持二进制 multipart。

**替代方案**：单一路由内根据 Content-Type header 分发。

**理由**：
- FastAPI 的 `Form + UploadFile` 依赖注入与 `Body(BaseModel)` 无法在同一端点共存
- 独立路由更清晰，且符合项目已有路由命名风格（`:upload`、`:create`、`:retrieve`）
```

Full source: openspec/changes/multi-format-parser/design.md

## openspec/changes/multi-format-parser/tasks.md

- Source: openspec/changes/multi-format-parser/tasks.md
- Lines: 1-67
- SHA256: e7d1f593be8831aeebf49d49963b526b5a85ab9d24a1e5bbce82cca217654a3d

```md
## 1. 领域模型扩展

- [ ] 1.1 扩展 `ParsedDocument`：增加 `source_type`（默认 "text"）和 `metadata`（默认 {}）字段
- [ ] 1.2 扩展 `Document`：增加 `source_file_path`、`source_filename` 字段
- [ ] 1.3 新增 `FileStoragePort` 协议：`save`/`read`/`delete` 方法
- [ ] 1.4 新增 `DOCUMENT_PARSE_FAILED` 错误码（20023，区间 10400-10499 文件与媒体）

## 2. Parser 插件层

- [ ] 2.1 新增 `adapters/parsers/registry.py`：按扩展名注册/选择 Parser，未匹配抛 `UNSUPPORTED_FORMAT`
- [ ] 2.2 新增 `adapters/parsers/docx.py`（DocxParser）：mammoth 转换 → Section 列表，标题 1/2 映射 `#`/`##`，表格映射 `| |`
- [ ] 2.3 新增 `adapters/parsers/pdf.py`（PdfParser）：PyMuPDF 按页抽取文字，每页加 `## 第 N 页` 标题
- [ ] 2.4 微调 `adapters/parsers/md_and_txt.py`：输出 `source_type="markdown"` 或 `"text"`
- [ ] 2.5 更新 `adapters/parsers/__init__.py`：导出 registry 和所有 parser

## 3. 文件存储适配器

- [ ] 3.1 新增 `adapters/file_storage/__init__.py` 和 `local.py`（LocalFileStorage）：实现 `FileStoragePort`
- [ ] 3.2 新增 `config.py` 配置项：`DOCUMENT_STORAGE_PATH`（默认 `./data/uploads`）、`DOCUMENT_MAX_SIZE_MB`（默认 20）

## 4. 数据库迁移

- [ ] 4.1 创建 Alembic migration：`documents` 表 ALTER ADD `source_file_path` TEXT、`source_filename` TEXT、`source_type` TEXT DEFAULT 'text'
- [ ] 4.2 更新 `PgDocumentRepository`：`create` 和 `get` 支持新字段
- [ ] 4.3 更新 `docs/sql/schema.sql`：同步 documents 表定义

## 5. 上传双模式

- [ ] 5.1 新增 `POST /v1/documents:upload-text` 路由（JSON body：`{kb_id, title, content}`）
- [ ] 5.2 扩展 `UploadDocumentUseCase`：支持 `file_path` 参数，二进制模式保存原文件 + content 置空
- [ ] 5.3 扩展 multipart upload 路由：`.docx`/`.pdf` 走二进制暂存模式，`.md`/`.txt` 保持现有行为
- [ ] 5.4 扩展 `allowed_exts` 为 `.md`、`.txt`、`.docx`、`.pdf`

## 6. 索引流水线编排

- [ ] 6.1 扩展 `IndexingService.execute()`：在 parse 前增加 `_prepare_content()` 步骤，从 `source_file_path` 读取并解析
- [ ] 6.2 更新 `di.py`（`_async_build_services`）：注入 registry parser 和 file_storage 依赖
- [ ] 6.3 更新 `composition.py`：组装新的 upload use case 和 document router

## 7. Reparse 支持

- [ ] 7.1 扩展 `DocumentReindexUseCase`：支持 `reparse=True` 参数，从原文件重新解析
- [ ] 7.2 扩展 `POST /v1/documents/{doc_id}/reindex`：新增 `reparse` query 参数

## 8. 前端改造

- [ ] 8.1 扩展 `file-filter.ts`：`ALLOWED_EXTS` 增加 `.pdf`、`.docx`；`MAX_SIZE` 改为配置化
- [ ] 8.2 扩展 `api.ts`：新增 `uploadDocJson(kb_id, title, content)` 调用 `/v1/documents:upload-text`
- [ ] 8.3 扩展 `upload-doc.tsx`：文件选择器 accept 增加 `.pdf,.docx`
- [ ] 8.4 可选：列表页 DocRow 展示格式 badge（`source_type`）

## 9. 依赖与构建

- [ ] 9.1 `pyproject.toml` 新增 `[project.optional-dependencies] parsers = ["mammoth>=1.6.0", "pymupdf>=1.24.0"]`
- [ ] 9.2 `Dockerfile` 安装 `.[parsers]` extra
- [ ] 9.3 `README.md` 补充 parsers 安装说明

## 10. 验证与测试

- [ ] 10.1 单元测试：DocxParser 解析 sample.docx（含标题和表格）→ sections 正确
- [ ] 10.2 单元测试：PdfParser 解析 sample.pdf（文字版）→ sections 含 `## 第 N 页`
- [ ] 10.3 单元测试：registry 按扩展名正确选择 parser
- [ ] 10.4 单元测试：`UploadDocumentUseCase` 双模式行为正确
- [ ] 10.5 集成测试：扫描件 PDF → `FAILED` + 明确错误信息
- [ ] 10.6 集成测试：JSON upload `.md` → 行为与改造前一致（回归）
- [ ] 10.7 E2E 验证脚本 `scripts/verify_multi_format.py`：docx/pdf/md 三种上传 → retrieve → 全部通过
- [ ] 10.8 运行现有测试套件确认零回归
```

