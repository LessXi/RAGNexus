# Task 4.x 实施报告 — SynonymExpander

## 状态: ✅ 完成

## 变更

| 文件 | 操作 | 行数 |
|------|------|------|
| `src/ragnexus/adapters/rewrite/synonym_expander.py` | 新增 | 78 |
| `tests/unit/test_synonym_expander.py` | 新增 | 131 |

## 实现

`SynonymExpander` 类，单一方法 `expand(effective_query, synonyms)`:

- **遍历** synonyms groups，对 terms 做子串匹配
- **中文精确子串匹配** + **英文 casefold 匹配**（`term.lower() in query_lower`）
- **命中组的 expand 词去重追加**，跨组也去重
- **格式异常静默跳过**：非 dict、缺键、terms/expand 非 list、含非字符串元素 — 均不抛异常
- **synonyms=None / []** → 返回原 query，`(query, False, [])`

## 测试场景 (7/7 通过)

| # | 测试 | 验证点 |
|---|------|--------|
| 1 | `test_single_group_hit` | 单组命中，扩展词追加到 query 末尾 |
| 2 | `test_multi_group_hit_dedup` | 多组命中，扩展词合并去重 |
| 3 | `test_no_match` | 未命中 → 返回原 query |
| 4 | `test_english_casefold` | "RAG" 命中 "rag" 的扩展词 |
| 5 | `test_empty_synonyms` | None/[] → 返回原 query |
| 6 | `test_malformed_synonyms_silent_skip` | 7 种畸形结构静默跳过，正常组仍生效 |
| 7 | `test_cross_group_expand_dedup` | 跨组相同扩展词只追加一次 |

## TDD 流程

- RED: 先写测试，确认 `ModuleNotFoundError`（实现文件不存在）
- GREEN: 实现 `SynonymExpander.expand()`，7/7 通过
- 全量回归: 350 pass, 1 fail（已有 `test_kb_repo.py` schema 不匹配，与本次无关）

## Commit

```
de9a970 feat(query): task 4.x — SynonymExpander 词表扩展器
```
