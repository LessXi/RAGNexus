# Task 2.7: PgKnowledgeBaseRepository 扩展

**状态**: ✅ 完成  
**文件**: `src/ragnexus/adapters/knowledge_base/pg.py`

## 变更摘要

在 `PgKnowledgeBaseRepository` 类中新增三个方法，完善 KB 知识库 CRUD 能力：

### 1. `update(kb_id, *, name=None, description=None, settings=None) -> KnowledgeBase`

- 动态构建 SET 子句，仅更新传入的非 None 字段
- 无任何字段变更时退化为 `get()` 查询
- `settings` 字段使用 `json.dumps(ensure_ascii=False)` 序列化后以 `::jsonb` 类型写入
- `RETURNING` 完整行后反序列化 JSONB（asyncpg 返回 str，需 `json.loads`）
- KB 不存在时抛出 `AppError(ErrorCode.NOT_FOUND)`

### 2. `delete(kb_id) -> None`

- `DELETE FROM knowledge_bases WHERE id = $1`
- 依赖外键 CASCADE 自动清理关联数据

### 3. `has_processing_docs(kb_id) -> bool`

- `SELECT 1 FROM documents WHERE kb_id=$1 AND status=2 LIMIT 1`
- 硬编码 `status=2`（对应 `DocStatus.PROCESSING`），避免循环导入

## 验收结果

```python
>>> from ragnexus.adapters.knowledge_base.pg import PgKnowledgeBaseRepository
>>> [m for m in dir(PgKnowledgeBaseRepository) if not m.startswith('_')]
['create', 'delete', 'doc_exists', 'exists', 'get', 'get_settings',
 'has_processing_docs', 'list_with_documents', 'update', 'update_settings']
```

三项新方法均已成功导入，验证通过。

## 设计决策

- **asyncpg JSONB 处理**: 遵循 AGENTS.md 最佳实践，`settings` 列读取后判断 `isinstance(raw, str)` → `json.loads()`，写入时 `json.dumps(ensure_ascii=False)`
- **硬编码 status=2**: 避免从 `ragnexus.domain.models` 导入 `DocStatus` 形成循环引用
- **动态 SQL**: `update` 方法仅拼接传入字段，避免覆盖未指定字段为 NULL
