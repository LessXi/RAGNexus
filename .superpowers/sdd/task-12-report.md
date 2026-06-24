# Task 12 Report: adapters/http/ — 3 Router Factories + Error Handlers

## Deliverables

### Files Created
| File | Purpose |
|---|---|
| `adapters/http/create_kb_router.py` | `create_router(uc)` → POST `/v1/knowledge-bases:create` |
| `adapters/http/upload_doc_router.py` | `create_router(uc)` → POST `/v1/documents:upload` (multipart) |
| `adapters/http/retrieve_router.py` | `create_router(uc)` → POST `/v1/rag:retrieve` |
| `adapters/http/error_handlers.py` | `register_error_handlers(app)` → DomainError → JSONResponse |
| `tests/unit/adapters/test_http.py` | 7 unit tests via FastAPI TestClient + mocked use cases |

### Files Modified
| File | Change |
|---|---|
| `pyproject.toml` | Added `python-multipart>=0.0.32` (runtime dep for FastAPI Form/UploadFile) |
| `uv.lock` | Updated by `uv add` |

## Test Results

### RED Phase (before implementation)
- ImportError: `ModuleNotFoundError: No module named 'adapters.http.create_kb_router'` (expected)

### GREEN Phase (after implementation)
- 7/7 tests passed, 1 warning (StarletteDeprecationWarning about httpx2)

**Test coverage:**

| Test | What it validates |
|---|---|
| `TestCreateKB::test_success` | 200 + `{code, data, message}` shape |
| `TestCreateKB::test_validation` | 422 for empty/too-long/missing name (pydantic) |
| `TestUploadDoc::test_success` | 201 + chunk_count in response |
| `TestUploadDoc::test_wrong_extension` | 415 via UnsupportedMediaTypeError |
| `TestRetrieve::test_success` | 200 + score rounded to 6dp |
| `TestRetrieve::test_extra_field` | 422 via pydantic `extra="forbid"` |
| `TestErrorHandler::test_domain_error_response` | 500 + `{code, data: null, message, errors}` |

All 62 existing unit tests also pass (no regressions).

## Design Decisions

1. **Factory pattern**: Each module exports `create_router(uc) -> APIRouter`. The injected use case is captured via closure — no class wrapper.

2. **Validations**:
   - Pydantic `extra="forbid"` on JSON models to reject unexpected fields (strict mode per spec).
   - Pydantic `min_length=1, max_length=64` on `CreateKBRequest.name` for early rejection.
   - Business validation (empty-after-strip, KB existence, etc.) is delegated to use cases — routers remain thin.

3. **upload_doc_router** uses FastAPI `Form()`/`UploadFile()` (multipart), not a pydantic model, since FastAPI's multipart handling works declaratively with form parameters.

4. **Error handler** maps `DomainError.http_status` to HTTP status, `DomainError.code` to `code`, `message_text` or `message` to `message`, and `errors` to `errors`. Data is always `null` for error responses.

## Nits / Potential Follow-ups

- `error_handlers.py` line `exc.message_text or exc.message` would `AttributeError` if someone raises bare `DomainError()` (no `message` class attr). All current subclasses define `message`, so this is safe today. Could use `getattr(exc, 'message', '内部错误')` as defensive belt.
- `python-multipart` is now a runtime dependency (not just dev). Already added to `pyproject.toml [project]` by `uv add`.
- The StarletteDeprecationWarning about `httpx2` can be resolved when the project upgrades, but has no functional impact.
