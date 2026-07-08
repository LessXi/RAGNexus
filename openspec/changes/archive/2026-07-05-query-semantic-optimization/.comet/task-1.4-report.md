# Task 1.4 实施报告

## 状态

✅ completed

## 变更摘要

`src/ragnexus/domain/models.py`：`KnowledgeBase` 模型新增 `settings: dict` 字段。

## TDD 循环

### RED — 验证字段不存在

```python
from src.ragnexus.domain.models import KnowledgeBase
kb = KnowledgeBase(id="kb_test1", name="测试KB", created_at=datetime.now(), tenant_id="t1")
assert not hasattr(kb, 'settings')  # 通过：字段尚未存在
```

### GREEN — 实现并验证

```python
# 新增字段定义（models.py 第 14 行）
settings: dict = field(default_factory=dict)  # KB 级配置: synonyms、rewrite_hint 等

# 验证
kb = KnowledgeBase(id="kb_test1", name="测试KB", created_at=datetime.now(), tenant_id="t1")
assert hasattr(kb, 'settings')     # ✓ 字段存在
assert kb.settings == {}           # ✓ 默认值为空字典
assert isinstance(kb.settings, dict)  # ✓ 类型为 dict

# 实例隔离验证
kb2 = KnowledgeBase(..., settings={"synonyms": {"AI": "人工智能"}})
assert kb.settings == {}  # ✓ 各实例 settings 互不共享
```

## 最终模型状态

```python
@dataclass
class KnowledgeBase:
    id: str  # "kb_" + nanoid(8)
    name: str  # user input
    created_at: datetime
    tenant_id: str = ""  # 租户ID，默认为空字符串（兼容旧数据）
    settings: dict = field(default_factory=dict)  # KB 级配置: synonyms、rewrite_hint 等
```

## Commit

```
cda5f5d feat(query): task 1.4 — KnowledgeBase 模型增加 settings 字段
```

## 约束满足

- ✅ 使用 `field(default_factory=dict)` 而非 `= {}`
- ✅ `from dataclasses import field` 已在文件第 3 行导入
- ✅ 字段位于 `tenant_id` 之后
- ✅ settings 存储 JSONB 兼容的 dict 配置
