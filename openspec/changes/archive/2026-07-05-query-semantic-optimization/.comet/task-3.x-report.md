# Task 3.x 实施报告 — llm.py 改写适配器变更

**时间**: 2026-07-05  
**Commit**: `b238408`  
**文件**: `src/ragnexus/adapters/rewrite/llm.py` (551→618 行)

## 变更摘要

| 任务 | 内容 | 状态 |
|------|------|------|
| 3.1 | RewriteResult→QueryProcessResult 字段替换 (14处) | ✅ |
| 3.2 | import/签名/类型注解更新 | ✅ |
| 3.3 | kb_context 注入 system prompt | ✅ |
| 3.4 | 内部计时 + degraded 标记 | ✅ |

## 详细变更

### 3.1-3.2: RewriteResult→QueryProcessResult

全部 14 处 RewriteResult 引用已替换为 QueryProcessResult：

| 位置 | 旧 | 新 |
|------|----|----|
| import (L23) | `RewriteResult` | `QueryProcessResult` |
| CacheEntry (L63) | `rewrite_result: RewriteResult` | `rewrite_result: QueryProcessResult` |
| rewrite() 返回 (L257) | `-> RewriteResult:` | `-> QueryProcessResult:` |
| rewrite() 构造 (L290-304) | `RewriteResult(original_query=...)` | `QueryProcessResult(raw_query=...)` 含全部10字段 |
| _rewrite_impl() 返回 (L319) | `-> RewriteResult:` | `-> QueryProcessResult:` |
| _rewrite_impl() LLM失败 (L333-344) | 4字段构造 | 10字段构造, degraded=True |
| _rewrite_impl() 解析降级 (L350-361) | 4字段构造 | 10字段构造, degraded=True |
| _rewrite_impl() 精炼失败 (L382-393) | 4字段构造 | 10字段构造, degraded=True |
| _rewrite_impl() 正常 (L398-409) | 4字段构造 | 10字段构造, degraded=False |
| _layer5_checks 返回 (L443) | `-> RewriteResult \| None:` | `-> QueryProcessResult \| None:` |
| _layer5_checks 为空 (L451-462) | 4字段构造 | 10字段构造 |
| _layer5_checks 相同 (L466-477) | 4字段构造 | 10字段构造 |
| _check_cache 返回 (L511) | `-> RewriteResult \| None:` | `-> QueryProcessResult \| None:` |
| _write_cache 参数 (L559) | `result: RewriteResult` | `result: QueryProcessResult` |

### 3.3: kb_context 注入

- `rewrite()` 新增 `kb_context: dict | None = None` 参数
- 在入口构建 `enhanced_prompt`：提取 name/description/rewrite_hint 拼接到 SYSTEM_PROMPT 后
- `_rewrite_impl()` 新增强制参数 `enhanced_prompt: str`
- `_call_llm()` 新增可选参数 `system_prompt: str = SYSTEM_PROMPT`

### 3.4: 内部计时与降级标记

- `rewrite()` 入口：`start_time = time.monotonic()`
- 正常路径：`latency_ms = int((time.monotonic() - start_time) * 1000)` 写入 `rewrite_latency_ms`
- 所有降级路径：`rewrite_latency_ms=0`, `degraded=True`, `degraded_reason=原因`
- 日志行 `rewritten_query` → `effective_query` 适配新字段名

## 验证

- ✅ `grep RewriteResult llm.py` — 零匹配
- ✅ `python -c "import ast; ast.parse(...)"` — 语法正确
- ✅ 所有 QueryProcessResult 构造包含完整 10 字段
- ✅ `synonym_applied=False`, `synonym_expansions=[]` 在所有构造中设置

## 注记

- `retrieve_use_case.py:122` 调用 `rewrite()` 无需修改 — `kb_context` 为可选参数
- `retrieve_use_case.py:123` 使用 `.rewritten_query` 需在后续任务中更新为 `.effective_query`
- 降级路径 `rewrite_latency_ms=0` 符合 QueryProcessResult docstring：`未改写时 = 0（哨兵值）`
