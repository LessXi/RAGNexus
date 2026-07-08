# Task 1.3 实施 Brief

## 任务

`domain/ports.py`：`KnowledgeBasePort` 增加 `get_settings(kb_id) -> dict` 和 `update_settings(kb_id, settings: dict)` 方法

## 当前状态

```python
class KnowledgeBasePort(Protocol):
    # 现有方法: get(kb_id), create(...), delete(kb_id), list(...)
    ...
```

## 变更

在 `KnowledgeBasePort` Protocol 中新增两个抽象方法：

```python
async def get_settings(self, kb_id: str) -> dict:
    """获取 KB 的 settings（JSONB）。"""
    ...

async def update_settings(self, kb_id: str, settings: dict) -> None:
    """更新（覆盖）KB 的 settings。"""
    ...
```

## 约束

- 维持 Protocol 风格（方法体为 `...`）
- 方法名与设计文档一致
- 放在现有方法之后，保持合理的分组
