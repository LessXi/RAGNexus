# Batch 1 审查报告 (Tasks 1.1-1.3)

## Spec Compliance

### Task 1.1 ✅ — `cross_kb_rrf_fuse`
All requirements met:
- Signature matches spec: `(kb_hits_groups: list[list[SearchHit]], k: int = 60) -> list[SearchHit]`
- RRF formula `1 / (k + rank_in_kb)` with rank starting at 1 — correct
- Dedup key `(doc_id, chunk_id)` — without `kb_id` — correct, confirmed by `test_duplicate_only_by_chunk_id_not_doc_id`
- Cross-KB RRF score summation: `rrf_scores[key] += contrib`
- First-seen preservation for `kb_id`/`text`/`metadata`
- Empty/single-group/multi-group/mixed-empty boundary handling all correct
- Test coverage: 10 cases in `test_fusion.py` — good

### Task 1.2 ⚠️ — `_retrieve_per_kb`
Signature matches ✅, vector/B25 calls correct ✅, in-KB RRF via `rrf_fuse` ✅, metadata marking (`_vector_score`/`_bm25_score`) ✅, three degradation scenarios (empty list paths) ✅.

**Exception handling gap**: spec states "不抛异常：降级是预期行为，不阻塞其他 KB". If `search_by_vector` or `search_by_keyword` throws (e.g., network error), the current method propagates the exception instead of degrading to the other pathway. The caller's `return_exceptions=True` catches it per-KB, but the intent is per-pathway degradation within a single KB — one pathway failure should not discard the other pathway's results. See [Important #2].

### Task 1.3 ❌ — `execute` 重构
per-KB parallel gather ✅, `per_kb_top_k = max(top_k, _vector_top_k, _bm25_top_k, 10)` ✅, `asyncio.gather(return_exceptions=True)` ✅, `cross_kb_rrf_fuse` wiring ✅, single-KB unified path ✅, query/embedding/rerank/logging preserved ✅.

**Regression: `vector_count`/`bm25_count` always 0**. Variables `vec_hits_raw` (line 142) and `kw_hits` (line 141) are initialized to `[]` but never reassigned after the old per-pathway code was removed. They feed into:
- `RetrieveResult.vector_count` (line 247)
- `RetrieveResult.bm25_count` (line 248)
- `_safe_log` `vector_hit_count` (line 266)
- `_safe_log` `keyword_hit_count` (line 267)

All four will always report 0. See [Critical #1].

## Strengths
- `cross_kb_rrf_fuse` tests are thorough: 2-group no-overlap, 2-group with overlap, single-group, empty, mixed-empty, cross-KB dedup, `(doc_id,chunk_id)` uniq test, 3-group sum, text/metadata preservation.
- `_retrieve_per_kb` tests cover all 4 operational scenarios (dual, vector-only, BM25-only, both empty).
- `execute` integration tests verify multi-KB parallelism, single-KB unified path, exception isolation, `per_kb_top_k` computation.
- Clean naming: `valid_groups`/`degraded_kb_ids` clear intent, `cross_kb_rrf_fuse` fast-path for empty input.
- `rrf_fuse` import retained, `cross_kb_rrf_fuse` import added — no dangling imports.

## Issues

### Critical (Must Fix)
1. **`vector_count` / `bm25_count` always 0** — `execute` lines 141-142 initialize `vec_hits_raw` and `kw_hits` to `[]`, but the old code that populated them (from `vec_result`/`kw_result`) was removed. They feed `RetrieveResult` and `_safe_log` with broken counts. Fix options: (a) have `_retrieve_per_kb` return a struct with per-pathway raw counts, aggregate in `execute`; (b) compute counts from `rrf_fuse` hits' metadata `_vector_score`/`_bm25_score` flags.

### Important (Should Fix)
1. **`degraded_kb_ids` collected but unused** — Variable populated per-KB (lines 207-219) but never surfaced in `RetrieveResult`, log aggregation, or response. Stakeholders lose visibility into which KBs were skipped/empty.
2. **`_retrieve_per_kb` doesn't catch per-pathway exceptions** — If `search_by_vector` throws, the method throws instead of degrading to BM25-only. The spec requires "不抛异常：降级是预期行为，不阻塞其他 KB". While `asyncio.gather(return_exceptions=True)` prevents cross-KB blocking, within a single KB one exception discards both pathways. Wrap each `search_by_*` call in try/except with empty-list fallback.

### Minor (Nice to Have)
1. In-place metadata mutation in `_retrieve_per_kb` (lines 385-386, 396-397) — modifies original SearchHit metadata dicts. Works because `rrf_fuse` creates new objects, but violates immutability.
2. `if not vec_hits and not kw_hits: return []` (line 400) is redundant — `rrf_fuse([], [], k=rrf_k)` already returns `[]`.
3. `test_retrieve_per_kb_returns_rank_ordered_hits` asserts partial ordering only; could verify exact RRF scores for stronger contract.

## Assessment: Needs fixes
- 1 Critical regression in response/logging correctness
- 2 Important issues (unused telemetry, exception handling gap)
- Minor cleanup items

**Must fix Critical #1 before merge.** Important items should be addressed in this batch.
