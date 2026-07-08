# Task 9 & 10: 上传双模式 + Reparse — 实现报告

## 改动清单

### 1. `src/ragnexus/application/upload_doc_use_case.py`
- `execute()` 新增二进制分支:
  - `.docx`/`.pdf` 检测 → `file_storage.save()` + content 置 `""` + `source_file_path`/`source_filename`
  - `.md`/`.txt` 保持文本解码路径，优先使用 `text_content` 参数
- `text_content` 参数已在之前添加，现正式使用

### 2. `src/ragnexus/adapters/http/upload_text_router.py` (新建)
- `POST /v1/documents:upload-text` — JSON body 上传
- `UploadTextRequest`: `{kb_id, title, content}`
- title 无扩展名自动追加 `.md`
- content_type 根据 title 后缀设为 `text/markdown` 或 `text/plain`
- 调用 `uc.execute(text_content=...)` 走文本路径

### 3. `src/ragnexus/composition.py`
- 导入并注册 `upload_text_router`
- `DocumentReindexUseCase` 构造传递 `file_storage`

### 4. `src/ragnexus/application/document_reindex_uc.py`
- 完整实现 `execute()` 方法
- `reparse=True` + `source_file_path` 存在 → `update_content(doc_id, content="")`
- 仅 FAILED 状态允许 reindex

### 5. `src/ragnexus/adapters/http/document_router.py`
- `POST /v1/documents/{doc_id}/reindex` 新增 `reparse: bool = False` 查询参数

### 6. 测试
- `tests/unit/application/test_upload_doc.py`:
  - `TestBinaryUpload` (4 tests): .docx, .pdf 二进制路径; .txt 保持文本; text_content 优先
  - `TestDocumentReindex` (5 tests): 正常 reindex; 文档不存在; 非 FAILED 状态; reparse 清除 content; reparse 无 source_path
- `tests/unit/adapters/test_http.py`:
  - `TestUploadText` (2 tests): JSON 上传 201 + 正确传参; 自动文件名补 `.md`
  - `TestDocumentReindexQuery` (1 test): reparse query 参数透传 (true/false/默认)

## 测试结果
- 新增测试 13 个全部 PASS
- 现有 75 个测试 0 回归（2 个 pre-existing feedback_router 失败与本改动无关）
