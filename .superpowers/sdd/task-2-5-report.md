# Task 2.5 — KnowledgeBasePort 扩展

## 变更内容

在 `src/ragnexus/domain/ports.py` 的 `KnowledgeBasePort` 类中新增三个方法：

1. **`update`** — 更新知识库元数据。接受 `kb_id` 和可选参数 `name`、`description`、`settings`，返回 `"KnowledgeBase"`（字符串引用避免循环导入）。使用 `*` 强制关键字参数保证调用清晰。
2. **`delete`** — 删除知识库。接受 `kb_id`，无返回值。
3. **`has_processing_docs`** — 检查知识库下是否有 `PROCESSING` 状态的文档。默认返回 `False`（具体实现在 `PgKnowledgeBaseRepository` 中）。

## 验证结果

```python
>>> from ragnexus.domain.ports import KnowledgeBasePort
>>> hasattr(KnowledgeBasePort, 'update')
True
>>> hasattr(KnowledgeBasePort, 'delete')
True
>>> hasattr(KnowledgeBasePort, 'has_processing_docs')
True
```

## Commit

`6ebc8ff` — `feat(domain): KnowledgeBasePort 扩展 update/delete/has_processing_docs`
