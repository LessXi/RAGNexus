# Task 8 Report: RetrieveUseCase

## Summary

Implemented `RetrieveUseCase` for vector retrieval across multiple knowledge bases.

## Files

- **Created**: `application/retrieve_use_case.py` — use case implementation
- **Created**: `tests/unit/application/test_retrieve.py` — test suite

## Test Results

### RED phase (before implementation)
Module import failed as expected: `ModuleNotFoundError: No module named 'application.retrieve_use_case'`

### GREEN phase (after implementation)
9 tests passed in 0.07s:

| Test | Status |
|---|---|
| `test_retrieve_success` | PASS |
| `test_query_empty` | PASS |
| `test_query_too_long` | PASS |
| `test_kb_ids_empty` | PASS |
| `test_kb_ids_too_many` | PASS |
| `test_top_k_oob` (0, 51) | PASS |
| `test_kb_not_found` | PASS |
| `test_multiple_kb_not_found` | PASS |
| `test_retrieve_log_fire_and_forget` | PASS |

### Regression
All 33 unit tests pass (24 existing + 9 new).

## Design Notes

- **Validation** follows spec §6.3: query 1–2000 chars, kb_ids 1–5, top_k 1–50
- **Score**: 1 - pgvector cosine distance, stored as float (normalized by adapter, not use case)
- **Logging**: fire-and-forget via `asyncio.create_task` in `finally` block; exceptions swallowed in `_safe_log`
- **Extended coverage** beyond brief: `test_query_too_long` (2000-char limit) and `test_kb_ids_too_many` (5-KB limit) per spec requirements
- Uses `unittest.mock.AsyncMock` for all async port mocks, consistent with project conventions

## Commit

```
git commit -m "feat: add RetrieveUseCase"
```
