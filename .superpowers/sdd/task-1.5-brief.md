# Task 1.5: kb_name 预加载与填充

## 文件
`src/ragnexus/application/retrieve_use_case.py` — `execute` 方法中，在跨库 RRF 融合后、rerank 前，添加 kb_name 填充逻辑。

## 依赖
- Task 1.4 已完成: `SearchHit` dataclass 有了 `kb_name: str = ""` 字段（默认值保证向后兼容）

## 实现要点

### 批量预加载
```python
# 批量预加载 kb_id → kb_name 映射
rows = await self._kb_repo.pool.fetch(
    "SELECT id, name FROM knowledge_bases WHERE id = ANY($1)", kb_ids
)
kb_names = {row["id"]: row["name"] for row in rows}
```

### 填充
在 `hits = cross_kb_rrf_fuse(valid_groups, k=rrf_k)` 之后立即填充：
```python
for hit in hits:
    hit.kb_name = kb_names.get(hit.kb_id, hit.kb_id[:8])
```

### 边界
- `kb_ids` 为空时 → `kb_names` 为空 dict，全部回退为 `kb_id[:8]`
- DB 中找不到 kb_id → 回退为 `kb_id[:8]`
- 使用 `self._kb_repo.pool.fetch` 进行原始 SQL 查询

### 位置（关键）
- **在跨库 RRF 融合之后**（`hits = cross_kb_rrf_fuse(...)` 之后）
- **在 rerank 之前**（如果有 rerank 逻辑）
- 放在 rerank 之前的原因是 rerank 可能需要 kb_name 信息

## 参考
- `self._kb_repo` — `KnowledgeBaseRepository` 实例
- `KnowledgeBase` model 有 `id` 和 `name` 字段
- asyncpg `pool.fetch` 返回 `list[asyncpg.Record]`

## 验证
- 正常路径: kb_name 正确填充
- 回退路径: 不存在的 kb_id → 取 `kb_id[:8]`
- 空 kb_ids 列表 → 不崩溃
