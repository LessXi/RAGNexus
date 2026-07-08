# Task 1.3 完成报告

## 任务

`KnowledgeBasePort` Protocol 新增 `get_settings` 和 `update_settings` 两个抽象方法。

## TDD 周期

### RED — 确认方法不存在

```
ast_grep: async def get_settings → No matches found
ast_grep: async def update_settings → No matches found
```

两方法均未存在于 KnowledgeBasePort，RED 确认。

### GREEN — 添加方法

在 `src/ragnexus/domain/ports.py:47-53` 新增：

```python
async def get_settings(self, kb_id: str) -> dict:
    """获取 KB 的 settings（JSONB）。"""
    ...

async def update_settings(self, kb_id: str, settings: dict) -> None:
    """更新（覆盖）KB 的 settings。"""
    ...
```

### GREEN 验证

```
grep: async def get_settings → 第47行，签名匹配
grep: async def update_settings → 第51行，签名匹配
```

## 变更文件

| 文件 | 操作 |
|------|------|
| `src/ragnexus/domain/ports.py` | `KnowledgeBasePort` 新增 2 个 Protocol 方法 |

## Commit

```
f840a43 feat(query): task 1.3 — KnowledgeBasePort 增加 settings 方法
```

## 验收确认

- [x] `get_settings(kb_id: str) -> dict` 存在，`...` 体
- [x] `update_settings(kb_id: str, settings: dict) -> None` 存在，`...` 体
- [x] 维持 Protocol 风格
- [x] commit 存在且 message 符合规范
