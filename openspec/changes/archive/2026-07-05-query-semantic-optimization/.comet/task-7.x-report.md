# Task 7.x Report — 全测试 RewriteResult→QueryProcessResult 适配

## 日期
2026-07-05

## 提交
`893eab3` — `test(query): stage 7 — 全测试 RewriteResult→QueryProcessResult 适配`

## 改动范围

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `tests/unit/test_rewrite_port.py` | 完全重写 | RewriteResult→QueryProcessResult，10 字段 + kb_context 测试 |
| `tests/unit/test_noop_rewrite.py` | 字段适配 | import, 类型注解, original/rewritten→raw/effective, reason→degraded=False |
| `tests/unit/test_llm_rewrite.py` | 字段适配 | 全量字段映射 + result.reason→degraded_reason(降级) / degraded=False(非降级) |
| `tests/integration/test_retrieve_full_chain.py` | 字段适配 | 残留 original_query/rewritten_query→raw_query/effective_query |
| `src/ragnexus/application/retrieve_use_case.py` | Bug 修复 | 生产代码残留 rewrite_result.rewritten_query→effective_query (1 行) |

## 字段映射

| 旧 RewriteResult | 新 QueryProcessResult | 测试适配 |
|-----------------|----------------------|---------|
| `original_query` | `raw_query` | 全部替换 |
| `rewritten_query` | `effective_query` | 全部替换 |
| `reason` | `degraded_reason`（降级时） / `degraded=False`（非降级） | 按场景分流 |
| _(无)_ | `search_query` | 新增断言 |
| _(无)_ | `strategy` | 新增断言 |
| _(无)_ | `rewrite_latency_ms` | 新增断言 |
| _(无)_ | `degraded` | 新增断言 |
| _(无)_ | `synonym_applied` | 新增断言 |
| _(无)_ | `synonym_expansions` | 新增断言 |

## 测试结果

```
tests/unit/test_llm_rewrite.py     .... 22 passed
tests/unit/test_noop_rewrite.py    ....  5 passed
tests/unit/test_rewrite_port.py    ....  6 passed
tests/unit/test_pipeline.py        ....  10 passed
tests/unit/application/            .... 38 passed (2 预存失败, 1 fixture 缺失)
—————————————————————————————————————————
迁移相关测试：81 passed, 0 failed
```

### 预存失败（非本次引入）
- `test_candidate_k_passed_to_keyword_search` — `RetrieveUseCase.__init__()` 缺 `reranker` 必选参数
- `test_rerank_result_is_returned` — 同上
- `test_hybrid_mode` — `fixture 'mock_rewriter' not found`

## 关键决策

1. **非降级 reason 断言处理**：生产代码中非降级 QueryProcessResult 的 `degraded_reason` 为 `None`，LLM 返回的 `reason` 仅通过日志记录。测试中：
   - 降级场景：`result.reason` → `result.degraded_reason` 保持不变
   - 非降级场景：原 `result.reason` 断言改为 `result.degraded is False`

2. **Protocol 签名更新**：`RewritePort.rewrite` 现在接受 `kb_context: dict | None = None` 参数，返回 `QueryProcessResult`。`test_rewrite_port.py` 完全重写覆盖这 3 个 keyword-only 参数 + 10 字段。

3. **生产代码遗漏修复**：`src/ragnexus/application/retrieve_use_case.py:163` 残留 `rewrite_result.rewritten_query`，在测试失败中被发现并修复为 `rewrite_result.effective_query`。

## 验收确认

- [x] `grep -rn RewriteResult src/ tests/` — 无匹配
- [x] `grep -r "\.original_query" src/ tests/` — 无匹配
- [x] `grep -r "\.rewritten_query" src/ tests/` — 无匹配
- [x] 迁移相关 81 个测试全部通过
- [x] commit `893eab3` 已提交
