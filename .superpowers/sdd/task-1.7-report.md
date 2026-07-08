# Task 1.7 Report: 多库词表合并

## 改动概述

在 `RetrieveUseCase.execute` 的 query 处理阶段前，批量加载所有 KB 的 settings 并合并 synonyms，按 `term` 去重。

## 修改文件

| 文件 | 改动 |
|------|------|
| `src/ragnexus/application/retrieve_use_case.py` | 替换单库 synonyms 加载为多库合并，新增 ~25 行 |
| `tests/unit/application/test_retrieve_use_case.py` | 新增 `test_multi_kb_synonyms_merged` 测试 + fixture 默认值修正 |
| `tests/unit/application/test_retrieve.py` | 更新 `test_scenario_12_7_cross_kb_isolation` 适配多库合并行为 |

## 实现细节

### retrieve_use_case.py — execute 方法 (lines 111-151)

原有代码只从 `primary_kb` (kb_ids[0]) 提取 synonyms。改为：

1. **保留 primary_kb 块**：仍用于 `kb_context`（name、description、rewrite_hint）
2. **新增多库循环**：遍历所有 `kb_ids`，从每个 KB 的 `settings.synonyms` 收集同义词
3. **按 term 去重**：`{s["term"]: s for s in all_synonyms}.values()`，后出现的覆盖前
4. **边界处理**：
   - KB 不存在 → `continue`
   - settings 为空/无 synonyms → `continue`
   - JSON 解析失败 → `logger.warning` + `continue`
   - synonym entry 缺 `term` 键 → 跳过（不参与去重）

### 测试

- **test_multi_kb_synonyms_merged**：3 KB，各有不同 synonyms（含 term 重复），验证合并去重（3 条 → 手机/电脑/平板），手机保留 kb2 版本
- **test_scenario_12_7**：更新为标准 synonym 格式 + 多库合并断言，验证 `side_effect` 序列正确

## 测试结果

```
tests/unit/application/ — 78 passed
```

## 边界覆盖

- [x] KB 返回 None → 跳过
- [x] settings = {} → 跳过
- [x] synonyms 缺失 → 跳过
- [x] JSON 解析失败 → warning + 跳过
- [x] term 重复 → dict 去重，后出现覆盖前
- [x] entry 缺 `term` 键 → 跳过不参与去重

## 提交

```
1e03090 feat: merge multi-KB synonyms in execute query processing
```

## Fix Round 1 (Batch 2 Review)

**Commit**: `eb3719b` — fix: batch 2 review — synonym key, rewrite_hint, merged get() loops

### 修复项

| ID | 级别 | 问题 | 修复 |
|----|------|------|------|
| C-1 | 🔴 Critical | Synonym 键名 `"term"` → 应为 `"terms"` | 去重逻辑改为 `"terms" in s and "expand" in s`，去重键改为 `frozenset(s.get("terms", []))` |
| I-1 | 🟡 Important | `rewrite_hint` 静默删除 | 纳入 `kb_contexts` 每个元素中；LLM 端格式化为 `[领域: {hint}]` |
| I-2 | 🟡 Important | 两次独立 `get()` 循环（2N 次 DB 查询） | 合并为单次遍历，每个 KB 只 `get()` 一次 |
| I-3 | 🟡 Important | `exists()` + `get()` 双重验证 | 因循环已合并，`get()` 调用从 3N 降至 2N（exists N + get N） |

### 修改文件

| 文件 | 改动 |
|------|------|
| `src/ragnexus/application/retrieve_use_case.py` | 合并 L111-147 两个循环为单次遍历；`"term"`→`"terms"`；新增 `rewrite_hint` 提取；JSON 解析失败后设置 `settings={}` 而非 `continue` |
| `src/ragnexus/adapters/rewrite/llm.py` | 恢复 `rewrite_hint` 格式化：`[领域: {hint}]` 追加到每行 KB 描述后 |
| `tests/unit/application/test_retrieve.py` | `test_scenario_12_7`：测试数据 `"term"`→`"terms"`、`"expansion"`→`"expand"`；`side_effect` 从 4 次减为 2 次；断言 `s["terms"][0]`、`s["expand"]` |
| `tests/unit/application/test_retrieve_use_case.py` | `test_multi_kb_synonyms_merged`：同上；`side_effect` 从 6 次减为 3 次；`test_multi_kb_rewrite_context`：`side_effect` 从 4 次减为 2 次 |

### 测试结果

```
tests/unit/ (excluding pre-existing feedback_router failure) — 572 passed
tests/unit/application/ — 79 passed
tests/unit/adapters/rewrite/ — 32 passed
```
