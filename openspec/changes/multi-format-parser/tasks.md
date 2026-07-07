## 1. 领域模型扩展

- [ ] 1.1 扩展 `ParsedDocument`：增加 `source_type`（默认 "text"）和 `metadata`（默认 {}）字段
- [ ] 1.2 扩展 `Document`：增加 `source_file_path`、`source_filename` 字段
- [ ] 1.3 新增 `FileStoragePort` 协议：`save`/`read`/`delete` 方法
- [ ] 1.4 新增 `DOCUMENT_PARSE_FAILED` 错误码（20023，区间 20020~20029 反馈/解析）

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

- [ ] 4.1 创建 Alembic migration：`documents` 表 ALTER ADD `source_file_path` TEXT、`source_filename` TEXT（`source_type` 复用 `content_type` 字段，不新增列）
- [ ] 4.2a 扩展 `DocumentPort.create()` 协议签名：增加 `source_file_path`、`source_filename` 可选参数
- [ ] 4.2b 新增 `DocumentPort.update_content(doc_id, content)` 方法：更新 `documents.content` 列（供 `_prepare_and_parse` 写入解析结果）
- [ ] 4.2c 更新 `PgDocumentRepository`：`create` 和 `get` 支持新字段，实现 `update_content`
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

- [ ] 9.1 `pyproject.toml` 新增 `[project.optional-dependencies] parsers = ["mammoth>=1.8.0", "pymupdf>=1.24.0"]`
- [ ] 9.2 `Dockerfile` 安装 `.[parsers]` extra
- [ ] 9.3 `README.md` 补充 parsers 安装说明

## 10. 验证与测试

- [ ] 10.1 单元测试：DocxParser 解析 sample.docx（含标题和表格）→ sections 正确
- [ ] 10.2 单元测试：PdfParser 解析 sample.pdf（文字版）→ sections 含 `## 第 N 页`；单页超 max_chars 时多 chunk 含相同 heading（已知限制，预期行为）
- [ ] 10.3 单元测试：registry 按扩展名正确选择 parser
- [ ] 10.4 单元测试：`UploadDocumentUseCase` 双模式行为正确
- [ ] 10.5 集成测试：扫描件 PDF → `FAILED` + 明确错误信息
- [ ] 10.6 集成测试：JSON upload `.md` → 行为与改造前一致（回归）
- [ ] 10.7 E2E 验证脚本 `scripts/verify_multi_format.py`：docx/pdf/md 三种上传 → retrieve → 全部通过
- [ ] 10.8 运行现有测试套件确认零回归
