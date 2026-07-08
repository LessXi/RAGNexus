# Task 2.2 实施 Brief

## 任务

`PgKnowledgeBaseRepository` 实现 `get_settings` / `update_settings`，create 时 settings 默认 `{}`

## 当前状态

`src/ragnexus/adapters/knowledge_base/pg.py` — `PgKnowledgeBaseRepository` 类已有 create、get、exists、list_with_documents 等方法。

## 变更

新增两个方法：

### get_settings

```python
async def get_settings(self, kb_id: str) -> dict:
    """获取 KB 的 settings（JSONB 列）。不存在时返回 {}。"""
    row = await self.pool.fetchrow(
        "SELECT settings FROM knowledge_bases WHERE id = $1", kb_id
    )
    if row is None:
        return {}
    return row["settings"] or {}
```

### update_settings

```python
async def update_settings(self, kb_id: str, settings: dict) -> None:
    """更新（覆盖）KB 的 settings。"""
    import json
    await self.pool.execute(
        "UPDATE knowledge_bases SET settings = $1::jsonb WHERE id = $2",
        json.dumps(settings, ensure_ascii=False),
        kb_id,
    )
```

### create 方法更新

在 `create()` 方法的 INSERT 语句中增加 `settings` 列，值为 `'{}'::jsonb`。

找到 `create()` 方法中的 INSERT 语句，增加 settings 列的插入。

## 约束

- 参考现有 `get()`、`exists()` 方法的代码风格
- get_settings 不存在时返回 `{}`，不返回 None
- update_settings 使用 `json.dumps(ensure_ascii=False)` 序列化
- create 新增 settings 默认 '{}'::jsonb
- 验证：需先运行 migration (task 2.1)
