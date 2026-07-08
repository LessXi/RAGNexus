# 批次 4+5 审查报告 — SynonymExpander + QueryPipeline

- **审查范围**: `src/ragnexus/adapters/rewrite/synonym_expander.py` (75 行)、`src/ragnexus/adapters/rewrite/pipeline.py` (97 行)、`tests/unit/test_synonym_expander.py` (134 行)、`tests/unit/test_pipeline.py` (204 行)，共 510 行
- **审查依据**: `docs/superpowers/specs/2026-07-05-query-semantic-optimization-design.md:85-91`（词表扩展规则）+ 全局约束
- **审查日期**: 2026-07-05
- **审查者**: Batch45Review

## 一、Spec Compliance 合规核对

| # | 规则 | 结果 | 证据 |
|---|------|------|------|
| 1 | 中文精确子串匹配 | ✅ | `synonym_expander.py:56` `term.lower() in query_lower`，对中文字符 `.lower()` 为恒等，等价精确子串 |
| 2 | 英文 casefold | ⚠️ 部分 | `synonym_expander.py:36,56` 使用 `.lower()` 而非 `.casefold()`。ASCII 范围等价，但非 ASCII（如德语 ß→ss）行为不同。详见发现 F-1 |
| 3 | 扩展词去重 | ✅ | `synonym_expander.py:62` `word not in all_expansions` 守卫追加，跨组去重 |
| 4 | 多组命中 expand 去重合并 | ✅ | 同一 `all_expansions` 列表跨组累积，`test_cross_group_expand_dedup` 验证 |
| 5 | 格式异常静默跳过 | ✅ | `synonym_expander.py:43-51,58-60,64-66` 多层 try/except + isinstance 守卫，`test_malformed_synonyms_silent_skip` 覆盖 8 类畸形 |
| 6 | 不抛异常 | ✅ | 所有异常路径 `continue`，无 raise |
| 7 | expand() 返回三元组 | ✅ | 签名 `-> tuple[str, bool, list[str]]`，所有路径返回三元组 |
| 8 | process() 签名 | ✅ | `(raw_query, kb_ids, kb_context, synonyms, enabled)` 与约束一致 |
| 9 | enabled=false → strategy="noop" | ✅ | `pipeline.py:54-66` 早返回，`test_disabled_returns_noop` 验证 |
| 10 | rewrite() 异常 → 捕获降级 | ✅ | `pipeline.py:68-83` try/except 包裹，`test_rewrite_exception_degraded` 验证 |
| 11 | synonym_applied 正确设置 | ✅ | enabled=false / 异常路径设 False；命中路径由 expand 返回值赋值 |
| 12 | synonym_expansions 正确设置 | ✅ | 同上，未扩展时为 `[]` |
| 13 | 跨 KB 隔离 | ✅ | expand() 仅消费传入的 synonyms，不持有全局状态 |

**合规小结**: 13 项规则 12 项完全合规，1 项（casefold）存在轻微实现偏差。

## 二、Code Quality 代码质量

| 维度 | 评估 | 说明 |
|------|------|------|
| 类型注解 | ✅ 良好 | `expand() -> tuple[str, bool, list[str]]`、`process() -> QueryProcessResult`、参数注解齐全；使用 `from __future__ import annotations` |
| 错误处理 | ✅ 合理 | expand() 防御式编程到位（dict/list/str 多层 isinstance）；pipeline 两级降级（异常捕获 + 内部 degraded 透传） |
| docstring | ✅ 清晰 | 中文 docstring 覆盖模块、类、公开方法，参数/返回值说明完整 |
| 测试覆盖 | ✅ 充分 | 7（expander）+ 5（pipeline）= 12 场景，命中/未命中/去重/异常/降级/noop/透传全覆盖 |
| 测试质量 | ⚠️ 小瑕疵 | 见 F-2（fixture 类型）、F-3（casefold 测试名不副实） |

## 三、Findings 发现

### F-1 [Minor] `casefold` 规则用 `.lower()` 实现，非 ASCII 行为有偏差

- **文件**: `src/ragnexus/adapters/rewrite/synonym_expander.py:36,56`
- **现象**: spec:88 明确要求"英文 casefold"，实现用 `effective_query.lower()` 和 `term.lower()`。
- **影响**: ASCII 范围（常规英文术语）`.lower()` 与 `.casefold()` 等价，不影响主用例。但 casefold 对非 ASCII（如 `ß`→`ss`、`İ`→`i̇`）更激进，spec 措辞选 casefold 即为覆盖此类。当前实现遇德语/土耳其语等术语会漏匹配。
- **建议**: 将两处 `.lower()` 替换为 `.casefold()`；测试补一条非 ASCII 用例（如 `STRASSE` vs `straße`）。
- **优先级**: Minor — 主路径不受影响，但属明确的 spec 措辞偏离。

### F-2 [Minor] 测试 fixture `rewrite_latency_ms=42.0` 为 float，与 `int` 注解不符

- **文件**: `tests/unit/test_pipeline.py:33`
- **现象**: `QueryProcessResult.rewrite_latency_ms: int`（`ports.py:160`），但 fixture 写 `rewrite_latency_ms=42.0`（float）。dataclass 不做运行时类型校验，故测试通过，但静态类型检查（pyright/mypy）会报赋值类型不符。
- **影响**: 仅测试代码风格问题，不影响生产行为。
- **建议**: 改为 `rewrite_latency_ms=42`（int 字面量）。
- **优先级**: Minor。

### F-3 [Minor] `test_english_casefold` 测试名声称 casefold，实际无法区分 casefold 与 lower

- **文件**: `tests/unit/test_synonym_expander.py:65-77`
- **现象**: 用例 `query="RAG 架构"`、`terms=["rag"]`，`RAG.lower()=="rag"` 与 `RAG.casefold()=="rag"` 结果相同，测试无法捕捉 F-1 的实现偏差。
- **影响**: 测试名给读者错误信心，认为 casefold 语义已被验证。
- **建议**: 补一条真正区分 casefold 的用例（如 `ß`/`İ`），或重命名测试为 `test_english_case_insensitive`。
- **优先级**: Minor。

### F-4 [Info] rewrite 异常降级路径 `strategy="rewrite"` 语义略含混

- **文件**: `src/ragnexus/adapters/rewrite/pipeline.py:78`
- **现象**: rewrite() 抛异常时返回 `strategy="rewrite"` + `needs_rewrite=False` + `degraded=True`。`strategy` 字段语义为"采用的策略"，rewrite 实际未完成却标 "rewrite"。
- **影响**: 不违反 spec（spec 仅约束 "rewrite"|"noop" 二值），且 `degraded=True` 已表达失败。下游消费 `strategy` 分支不受影响。仅语义层面略含混。
- **建议**: 可保留现状（与内部降级路径一致），或在 spec 中明确"attempted strategy"语义。无需强制修改。
- **优先级**: Info — 非缺陷，记录备查。

### F-5 [Info] 异常降级跳过 expand，内部降级却执行 expand — 行为不对称

- **文件**: `src/ragnexus/adapters/rewrite/pipeline.py:68-83` vs `pipeline.py:85-93`
- **现象**: rewrite() 抛异常 → 早返回，跳过 expand（`test_rewrite_exception_degraded` 验证 `synonym_applied is False`）；rewrite() 返回 degraded=True → 继续执行 expand（`test_rewrite_internal_degradation_passthrough` 验证 `synonym_applied is True`）。两种降级路径对扩展的处理不一致。
- **影响**: 这是代码路径结构决定的（异常早返回 vs 正常返回继续），spec 未明确要求统一。内部降级时 effective_query 可用（=raw_query），追加扩展词对检索有益，行为合理。异常路径无法保证 effective_query 可用，跳过更安全。
- **建议**: 保留现状；建议在 docstring 或 spec 注明此不对称为有意设计。
- **优先级**: Info — 非缺陷，记录备查。

## 四、最终判定

### **APPROVED** （附带 Minor 建议）

**理由**:
- 13 项 spec 规则中 12 项完全合规，1 项（casefold）仅非 ASCII 边缘场景有偏差，主路径（中英文术语）行为正确。
- 代码质量良好：类型注解完整、错误处理防御到位、docstring 清晰、12 个测试场景覆盖全面（命中/未命中/去重/异常/降级/noop/透传/畸形容错）。
- 4 个 Minor/Info 发现均非阻塞：F-1/F-3 是 casefold 语义边缘偏差，F-2 是测试 fixture 类型风格，F-4/F-5 是语义注记。
- 无 Critical、无 Important 级问题；无数据损坏、安全、功能性缺陷。

**建议跟进（非阻塞）**:
1. F-1: 将 `.lower()` 改为 `.casefold()` 并补非 ASCII 测试用例
2. F-2: fixture `42.0` → `42`
3. F-3: 测试重命名或补充真正区分 casefold 的用例

| 严重度 | 数量 |
|--------|------|
| Critical | 0 |
| Important | 0 |
| Minor | 3 (F-1, F-2, F-3) |
| Info | 2 (F-4, F-5) |
