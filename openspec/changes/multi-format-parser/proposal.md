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
- **扩展** Document 模型和数据库表，增加 `source_file_path`、`source_filename` 字段（`source_type` 复用现有 `content_type` 字段）
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
- **数据库**: `documents` 表新增 2 列（migration）
- **API**: 新增 `POST /v1/documents:upload-text`；扩展 reindex 支持 `reparse` 参数
- **前端**: `file-filter.ts` 扩展格式；`upload-doc.tsx` 适配双模式
- **依赖**: 新增 `mammoth>=1.8.0`、`pymupdf>=1.24.0` 可选依赖组 `[parsers]`
- **不受影响**: 切块、embedding、ES/pgvector、检索、知识库管理、租户、配额、限流
