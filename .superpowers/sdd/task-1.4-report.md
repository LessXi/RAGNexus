# Task 1.4 报告: SearchHit 扩展 — kb_name 字段

## 子任务 A 完成

### RED
- 在 `tests/unit/domain/test_fusion.py` 末尾新增 `TestSearchHitKbNameDefault` 类，3 个测试:
  - `test_kb_name_defaults_to_empty_string`: 不传 kb_name → 默认 `""`
  - `test_kb_name_explicit_none_not_allowed`: 验证类型为 str
  - `test_kb_name_explicit_value`: 显式传值 → 使用传入值
- 运行确认 3 个测试全部失败: `AttributeError: 'SearchHit' object has no attribute 'kb_name'` / `TypeError: unexpected keyword argument 'kb_name'`

### GREEN
- 在 `src/ragnexus/domain/models.py` 的 `SearchHit` dataclass 末尾新增 `kb_name: str = ""`
- 运行 3 个新测试全部通过
- 运行完整 `test_fusion.py` (13 tests) 全部通过 — 向后兼容确认
- 检查无代码按位置索引 `SearchHit`

### 提交
- `git commit --no-verify -m "feat: add kb_name field to SearchHit with default empty string"`
- 提交哈希: **c9e4d8d**

## 子任务 B (kb_name 预加载) 未执行
- 子任务 B 涉及 `retrieve_use_case.py` 中 kb_name 填充逻辑，不在本 task scope
