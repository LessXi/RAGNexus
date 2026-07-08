# Task 1.4 实施 Brief

## 任务

`domain/models.py`：`KnowledgeBase` 模型增加 `settings: dict` 字段（默认 `{}`）

## 当前状态

`src/ragnexus/domain/models.py` 第 8-13 行：

```python
@dataclass
class KnowledgeBase:
    id: str  # "kb_" + nanoid(8)
    name: str  # user input
    created_at: datetime
    tenant_id: str = ""  # 租户ID，默认为空字符串（兼容旧数据）
```

## 变更

在 `tenant_id` 之后新增 `settings` 字段：

```python
settings: dict = field(default_factory=dict)  # KB 级配置: synonyms、rewrite_hint 等
```

## 约束

- 使用 `field(default_factory=dict)` 而非 `= {}`（dataclass 可变默认值最佳实践）
- 确保 `from dataclasses import field` 已在导入中（检查文件第 3 行：`from dataclasses import dataclass, field` — 已有 `field`）
- settings 存储 JSONB 兼容的配置（synonyms 词表、rewrite_hint 等）
