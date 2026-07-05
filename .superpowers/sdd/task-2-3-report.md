# Task 2.3 — DocNode/KBNode 适配

## 操作
- **文件**: `src/ragnexus/domain/models.py`
- **变更**: DocNode dataclass 添加 `error_message: str | None = None` 字段

## 验证
```python
>>> from ragnexus.domain.models import DocNode
>>> d = DocNode(doc_id='d1', filename='f.txt', status='processing', uploaded_at='2024-01-01', error_message='err')
>>> print(d.error_message)
err
```

## 结论
✅ 变更完成，KBNode 未修改（description 已由 Task 1.5 schema.sql 同步）。
