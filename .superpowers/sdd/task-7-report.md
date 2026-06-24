# Task 7 Report: UploadDocumentUseCase

## Summary

Implemented `UploadDocumentUseCase` following spec §6.2 / §12.2 with TDD approach.

## RED (Test First)

**File:** `tests/unit/application/test_upload_doc.py`

6 test cases with mock ports covering the full pipeline:

| Test | Assertion |
|---|---|
| `test_upload_success` | Returns `UploadResult` with correct `doc_id` (SHA256[:16] with `doc_` prefix, matching `kb_id`, non-empty chunks, all metadata fields present, `store.upsert` called) |
| `test_file_too_large` | `PayloadTooLargeError` (code 1301) when filesize > 10MB |
| `test_wrong_extension` | `UnsupportedMediaTypeError` (code 1300) for `.pdf`/`.docx`/`.png`/no-ext |
| `test_kb_not_found` | `NotFoundError` (code 1100) when `kb_repo.exists()` returns False |
| `test_duplicate_doc` | `DuplicateDocumentError` (code 1201) when `doc_exists()` returns True; parser NOT called |
| `test_empty_file` | `EmptyFileError` (code 1400) when parser returns empty sections + raw_text |

**RED output:** `ModuleNotFoundError: No module named 'application.upload_doc_use_case'`

## GREEN (Implementation)

**File:** `application/upload_doc_use_case.py`

- Constructor accepts: `kb_repo`, `parser`, `embedder`, `chunker` (Callable), `store`, plus configurable `max_file_size`, `allowed_exts`, `chunk_max_chars`, `chunk_overlap`
- `execute(kb_id, file_content, filename, content_type)` implements the 10-step pipeline:
  1. File size guard → `PayloadTooLargeError`
  2. Extension check → `UnsupportedMediaTypeError`
  3. KB existence → `NotFoundError`
  4. `doc_id = "doc_" + SHA256(file_content).hexdigest()[:16]`
  5. Dedup → `DuplicateDocumentError` (before parsing)
  6. Parse via injected `ParserPort`
  7. Chunk via injected chunker (spec: `heading_aware_split`)
  8. Embed via `EmbedderPort`
  9. Construct `Chunk` list with `common_meta` + `chunk_index`
  10. Transactional `store.upsert` → return `UploadResult`

- Metadata: chunk-level `{chunk_index}` + doc-level `{filename, file_hash, file_size, content_type}`

## Verification

**GREEN output:** `pytest: 6 passed in 0.06s`

## Commit

```
9a791d5 feat: add UploadDocumentUseCase
  application/upload_doc_use_case.py  | 122 +++++++++++++++++++++++++++
  tests/unit/application/test_upload_doc.py | 220 ++++++++++++++++++++++++++++++++++
```
