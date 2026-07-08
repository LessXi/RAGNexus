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
