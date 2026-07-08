# Stage 12 验收场景验证报告

**日期**: 2026-07-05
**状态**: ✅ 全部通过 — 11/11 场景有测试覆盖或代码证据
**总测试数**: 415 passed, 0 failed

---

## 场景覆盖矩阵

| # | 场景描述 | 状态 | 证据 |
|---|---------|------|------|
| 12.1 | 不传 query_options + 无 settings → behavior unchanged, query_processing=null | ✅ COVERED | 见下 |
| 12.2 | query_options.enabled=true + LLM 正常 → effective≠raw, needs_rewrite=true | ✅ COVERED | 见下 |
| 12.3 | LLM 不可用 → degraded=true, effective==raw, code=0 | ✅ COVERED | 见下 |
| 12.4 | 词表命中 → synonym_applied=true, search_query 含扩展词 | ✅ COVERED | 见下 |
| 12.5 | 有词表但未命中 → synonym_applied=false, search_query==effective_query | ✅ COVERED | 见下 |
| 12.6 | 多组词表命中 → 扩展词去重合并 | ✅ COVERED | 见下 |
| 12.7 | 跨库隔离 → KB_A 词表不影响 KB_B | ✅ COVERED | 见下 |
| 12.8 | 改写+词表同开 → raw→effective→search 三阶段 | ✅ COVERED | 见下 |
| 12.9 | 开改写但无词表 → effective≠raw, synonym_applied=false, search==effective | ✅ COVERED | 见下 |
| 12.10 | enabled=false + strategy="rewrite" → enabled 优先, query_processing=null | ✅ COVERED | 见下 |
| 12.11 | 调试台勾选改写 → 运行摘要展示对比；无处理时不展示 | ✅ CODE-VERIFIED | 见下 |

---

## 逐场景详细证据

### 12.1 — no query_options + no settings → behavior unchanged

**Multi-layer coverage:**

1. **Pipeline 层** — `tests/unit/test_pipeline.py::TestQueryPipeline::test_disabled_returns_noop`
   - 验证：enabled=False → strategy="noop"，三阶段相同，rewriter 未调用

2. **UseCase 层** — `tests/unit/application/test_retrieve.py::test_scenario_12_1_no_query_options_noop` *(新增)*
   - 验证：不传 query_options + env `QUERY_REWRITE_ENABLED` 未设 → pipeline 以 enabled=False 调用
   - 验证：`RetrieveResult.query_processing` 存在但 strategy="noop", synonym_applied=False
   - 在 router 层会被过滤为 null（见 router 逻辑分析）

3. **Router 层** — `src/ragnexus/adapters/http/retrieve_router.py:111-114`
   ```python
   qp = result.query_processing
   query_processing = None
   if qp and (qp.get("strategy") != "noop" or qp.get("synonym_applied")):
       query_processing = qp
   ```
   当 strategy="noop" 且 synonym_applied=False → HTTP 响应 `query_processing` 为 null

---

### 12.2 — enabled=true + LLM 正常 → effective≠raw, needs_rewrite=true

**`tests/unit/test_pipeline.py::TestQueryPipeline::test_rewrite_and_expand_both_enabled`**
```python
assert result.raw_query == "今天天气怎么样"
assert result.effective_query == "今天天气如何"  # ≠ raw
assert result.needs_rewrite is True
assert result.strategy == "rewrite"
```

---

### 12.3 — LLM 不可用 → degraded=true, effective==raw, code=0

**`tests/unit/test_pipeline.py::TestQueryPipeline::test_rewrite_exception_degraded`**
```python
assert result.degraded is True
assert "LLM 超时" in (result.degraded_reason or "")
assert result.effective_query == result.raw_query
assert result.needs_rewrite is False
```

**code=0 保证**：pipeline 异常不传播（被捕获为降级结果）→ use case 正常继续 → router 固定返回 `"code": 0`（`retrieve_router.py:117`）

---

### 12.4 — 词表命中 → synonym_applied=true

**`tests/unit/test_synonym_expander.py::TestSynonymExpander::test_single_group_hit`**
```python
assert applied is True
assert "背景调查" in result
assert query in result  # 原查询保留
assert "背景调查" in expansions
```

---

### 12.5 — 词表未命中 → synonym_applied=false

**`tests/unit/test_synonym_expander.py::TestSynonymExpander::test_no_match`**
```python
assert applied is False
assert result == query  # search_query == effective_query (未变化)
assert expansions == []
```

---

### 12.6 — 多组命中 → 去重合并

**`tests/unit/test_synonym_expander.py::TestSynonymExpander::test_multi_group_hit_dedup`**
- 验证：两组命中，扩展词去重后正确合并

**`tests/unit/test_synonym_expander.py::TestSynonymExpander::test_cross_group_expand_dedup`**
- 验证：跨组扩展词去重（"背景调查" 只出现一次）

---

### 12.7 — 跨库隔离

**`tests/unit/application/test_retrieve.py::test_scenario_12_7_cross_kb_isolation`** *(新增)*
```python
# KB_A 有 synonyms: [AI → 人工智能]
# KB_B 有 synonyms: [ML → 机器学习]
# kb_ids = ["kb_a", "kb_b"] → 只读取 kb_ids[0]（KB_A）的 settings
mock_kb_repo.get.assert_awaited_once_with("kb_a")
call_kwargs["synonyms"] == [{"terms": ["AI"], "expand": ["人工智能"]}]
```

**代码保证**：`retrieve_use_case.py:108-120` 只调用了 `self._kb_repo.get(kb_ids[0])`，永远只使用主 KB 的 settings。

---

### 12.8 — 改写+词表同开 → 三阶段完整且可不同

**`tests/unit/test_pipeline.py::TestQueryPipeline::test_rewrite_and_expand_both_enabled`**
```python
assert result.raw_query == "今天天气怎么样"           # Stage 1: raw
assert result.effective_query == "今天天气如何"        # Stage 2: effective (≠ raw)
assert result.effective_query != result.search_query   # Stage 3: search (≠ effective)
assert "气候" in result.search_query                  # 扩展词已追加
```

---

### 12.9 — 开改写但无词表 → synonym_applied=false, search==effective

**`tests/unit/test_pipeline.py::TestQueryPipeline::test_rewrite_only_no_synonyms`**
```python
assert result.effective_query == "今天天气如何"       # 改写生效
assert result.search_query == result.effective_query   # 无扩展, search==effective
assert result.synonym_applied is False
assert result.synonym_expansions == []
```

---

### 12.10 — enabled=false 优先于 strategy

**Multi-layer coverage:**

1. **Pipeline 层** — `tests/unit/test_pipeline.py::TestQueryPipeline::test_disabled_returns_noop`
   - enabled=False → noop, rewriter 未调用

2. **UseCase 层** — `tests/unit/application/test_retrieve.py::test_scenario_12_10_enabled_false_priority` *(新增)*
   ```python
   query_options={"enabled": False, "strategy": "rewrite"}
   # pipeline 被 enabled=False 调用
   call_kwargs["enabled"] is False
   # query_processing 为 noop（router 会过滤为 null）
   result.query_processing["strategy"] == "noop"
   result.query_processing["needs_rewrite"] is False
   ```

3. **Router 层** — 同 12.1 的 null 过滤逻辑

---

### 12.11 — 调试台勾选改写 → 运行摘要展示对比

**Frontend 代码证据** (`admin/src/pages/retrieve.tsx`):

- **勾选框** (line 324)：`<span>启用 query 改写</span>` + HelpTooltip
- **发送请求** (line 120)：`body.query_options = { enabled: true, strategy: 'rewrite' }`
- **摘要展示** (line 549)：`{meta.query_processing && (` — 仅当有值时展示
  - 显示「原话」「改写后」「最终检索句」三阶段对比 (lines 557-566)
  - 显示 `rewrite_latency_ms` (line 573)
  - 降级提示：`meta.query_processing.degraded &&` (line 578) + 红色告警框
  - 扩展词列表：`meta.query_processing.synonym_expansions.length > 0 &&` (line 591) + 标签展示
- **无处理时不展示**：`query_processing` 为 null/falsy → 整个摘要区块不渲染

> 本项目无前端自动化测试框架；场景 12.11 通过 **代码审查** 验证，确认 toggle 发送参数和条件渲染逻辑与 spec 一致。

---

## 新增测试清单

| # | 文件 | 测试方法 | 覆盖场景 |
|---|------|---------|---------|
| 1 | `tests/unit/application/test_retrieve.py` | `test_scenario_12_1_no_query_options_noop` | 12.1 |
| 2 | `tests/unit/application/test_retrieve.py` | `test_scenario_12_7_cross_kb_isolation` | 12.7 |
| 3 | `tests/unit/application/test_retrieve.py` | `test_scenario_12_10_enabled_false_priority` | 12.10 |

---

## 测试运行结果

```
$ python -m pytest tests/unit/ -q
415 passed, 1 warning in 23.05s
```

关键测试文件：
```
tests/unit/test_pipeline.py ............. 5 passed
tests/unit/test_synonym_expander.py .... 7 passed
tests/unit/application/test_retrieve.py  22 passed (含 3 新增)
```

---

## 结论

全部 11 个验收场景已覆盖：
- **7 个场景**由现有测试直接覆盖（12.2–12.6, 12.8, 12.9）
- **3 个场景**新增 use case 层测试覆盖（12.1, 12.7, 12.10）
- **1 个场景**前端代码审查验证（12.11）

所有 415 个测试通过，stage 12 验收完成。
