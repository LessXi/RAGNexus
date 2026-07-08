# Task 3.5 Report — noop.py 适配

## 状态: ✅ 完成

## 修改文件

`src/ragnexus/adapters/rewrite/noop.py` (33→44行)

## 变更摘要

1. **import**: `RewriteResult` → `QueryProcessResult`
2. **rewrite() 签名**: 新增 `kb_context: dict | None = None` 参数
3. **返回类型**: `RewriteResult` → `QueryProcessResult`
4. **字段映射**:

| 旧字段 | 新字段 | 值 |
|---|---|---|
| `original_query` | `raw_query` | `query` |
| `rewritten_query` | `effective_query` | `query` |
| — | `search_query` | `query` |
| `needs_rewrite` | `needs_rewrite` | `False` |
| `reason` | (移除) | — |
| — | `strategy` | `"noop"` |
| — | `rewrite_latency_ms` | `0` |
| — | `degraded` | `False` |
| — | `degraded_reason` | `None` |
| — | `synonym_applied` | `False` |
| — | `synonym_expansions` | `[]` |

5. **docstring**: 更新为三阶段 query 语义说明

## 验证

- `grep RewriteResult src/ragnexus/adapters/rewrite/noop.py`: **0 匹配** ✅
- `strategy="noop"` ✅ (区别于 llm.py 的 `"rewrite"`)
- `kb_context` 参数存在 ✅
- 全部 10 字段初始化 ✅

## Commit

```
feat(query): task 3.5 — noop.py RewriteResult→QueryProcessResult
```
