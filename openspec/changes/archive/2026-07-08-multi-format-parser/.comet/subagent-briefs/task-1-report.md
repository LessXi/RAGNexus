# Task 1 Report: 领域模型扩展

## Status
**DONE**

## 变更文件
- `src/ragnexus/domain/models.py` — ParsedDocument: +source_type, +metadata；Document: +source_file_path, +source_filename
- `src/ragnexus/domain/ports.py` — ParserPort 后新增 FileStoragePort 协议
- `src/ragnexus/core/errors.py` — FEEDBACK_INVALID_SCORE 后新增 DOCUMENT_PARSE_FAILED (20023, 422)
- `tests/unit/domain/test_models.py` — 新增 test_parsed_document_defaults + test_document_new_fields_default_none

## RED 证据

```bash
$ uv run pytest tests/unit/domain/test_models.py -v
# 输出:
# FAILED test_parsed_document_defaults - AttributeError: 'ParsedDocument' object has no attribute 'source_type'
# FAILED test_document_new_fields_default_none - AttributeError: 'Document' object has no attribute 'source_file_path'
# 2 failed, 8 passed
```

## GREEN 证据

```bash
$ uv run pytest tests/unit/domain/test_models.py tests/unit/application/test_upload_doc.py tests/unit/application/test_indexing_service.py tests/unit/adapters/test_parser.py -v
# 输出:
# 42 passed in 0.49s
```

## Commit
```
19f3eda8c83ad34bb90897a6e542de4f3ba8a6ef
feat: extend domain models for multi-format parsing
```

## 顾虑
无。ParsedDocument 新字段有默认值（source_type="text", metadata=field(default_factory=dict)），因此引用 ParsedDocument 的现有测试不需要修改——零破坏。
