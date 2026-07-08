# Task 5.x 完成报告 — QueryPipeline

## 状态: ✅ 完成

## 产出

| 文件 | 说明 |
|------|------|
| `src/ragnexus/adapters/rewrite/pipeline.py` | QueryPipeline 实现 (96 行) |
| `tests/unit/test_pipeline.py` | 5 个测试场景 (204 行) |

## 实现概要

### QueryPipeline 类

```python
class QueryPipeline:
    def __init__(self, rewriter: RewritePort, expander: SynonymExpander)
    async def process(self, raw_query, kb_ids, kb_context=None, synonyms=None, enabled=True) -> QueryProcessResult
```

### process() 逻辑

1. **enabled=false**: 返回 noop `QueryProcessResult`（strategy="noop"，三阶段相同）
2. **enabled=true**:
   - 调用 `rewriter.rewrite(query=raw_query, kb_ids=kb_ids, kb_context=kb_context)` 获取改写结果
   - 若 synonyms 非空，调用 `expander.expand(result.effective_query, synonyms)` 覆盖 search_query/synonym 字段
3. **rewrite() 异常**: 捕获并返回 degraded `QueryProcessResult`（strategy="rewrite", degraded=True, degraded_reason=str(exc)）

## 测试结果

```
tests/unit/test_pipeline.py::test_rewrite_and_expand_both_enabled PASSED
tests/unit/test_pipeline.py::test_rewrite_only_no_synonyms PASSED
tests/unit/test_pipeline.py::test_disabled_returns_noop PASSED
tests/unit/test_pipeline.py::test_rewrite_exception_degraded PASSED
tests/unit/test_pipeline.py::test_rewrite_internal_degradation_passthrough PASSED

5 passed in 0.21s
```

### 场景覆盖

| # | 场景 | 验证点 |
|---|------|--------|
| 1 | 改写+扩展同开 | effective≠raw, search≠effective, synonym_applied=True |
| 2 | 仅改写 (synonyms=None) | effective≠raw, search==effective |
| 3 | enabled=false | strategy="noop", 三阶段相同, rewriter 未调用 |
| 4 | rewrite 异常降级 | degraded=True, effective==raw, 不抛异常 |
| 5 | rewrite 内部降级透传 | degraded=True 透传, 扩展仍执行 |

## Commit

```
bdf0e40 feat(query): task 5.x — QueryPipeline 串联改写+扩展
```
