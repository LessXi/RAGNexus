# Task 2.2 Report — PgKnowledgeBaseRepository get_settings / update_settings

## 状态: ✅ 完成

## 变更摘要

`PgKnowledgeBaseRepository` 新增两个方法 + 修改 `create()` 的 INSERT 语句以包含 `settings` 列。

### 新增方法

| 方法 | 签名 | 行为 |
|------|------|------|
| `get_settings` | `(kb_id: str) -> dict` | 查询 settings JSONB 列，KB 不存在或 settings 为 NULL 时返回 `{}` |
| `update_settings` | `(kb_id: str, settings: dict) -> None` | 用 `json.dumps(ensure_ascii=False)` 序列化后覆盖写入 settings |

### create() 修改

- INSERT 列列表增加 `settings`
- VALUES 增加 `$5::jsonb` 占位符，参数传 `"{}"`
- RETURNING 增加 `settings`
- `KnowledgeBase` 构造增加 `settings=row["settings"] or {}`

## 文件变更

| 文件 | 变更 |
|------|------|
| `src/ragnexus/adapters/knowledge_base/pg.py` | +28 行：`get_settings`(10行)、`update_settings`(8行)、`create()` INSERT 修改(2行)、KnowledgeBase 构造修改(1行) |
| `tests/unit/adapters/test_kb_repo.py` | +59 行：`TestGetSettings`(3 tests)、`TestUpdateSettings`(1 test)、`test_create_success` 更新 |

## TDD 验证

```
RED:  4 new tests fail — AttributeError (方法不存在)           ✅
GREEN: 12/12 unit tests pass                                 ✅
REFACTOR: 无需重构，代码简洁                                  ✅
```

- `test_get_settings_found` — mock 返回 settings dict → 断言返回正确 dict
- `test_get_settings_not_found` — mock 返回 None → 断言返回 `{}`
- `test_get_settings_null` — mock 返回 `{"settings": None}` → 断言返回 `{}`
- `test_update_settings_calls_execute` — 验证 execute 被调用，SQL 和参数正确
- `test_create_success` 已更新 — mock 和断言包含 `settings: {}`

## Commit

```
b92aea8 feat(query): task 2.2 — PgKBRepo get_settings/update_settings
```

## 风险

无。新方法不改变现有 API 契约；集成测试因环境无 PostgreSQL 实例无法运行，但属于预置条件问题，非本次变更引入。
