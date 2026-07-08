# Task 1.4: SearchHit 扩展 + kb_name 预加载

## 子任务 A: SearchHit 新增 `kb_name` 字段

### 文件
`src/ragnexus/domain/models.py` — 修改 `SearchHit` dataclass

### 改动
在 `SearchHit` dataclass 末尾新增字段：
```python
kb_name: str = ""  # 知识库名称，便于前端 Badge 展示
```

### 注意
- 默认值 `""` 确保向后兼容 — 所有现有的 `SearchHit(...)` 构造代码无需修改
- 数据类字段顺序：`chunk_id, kb_id, doc_id, score, text, metadata, kb_name`

## 子任务 B: kb_name 预加载与填充

### 文件
`src/ragnexus/application/retrieve_use_case.py` — `execute` 方法中新增填充逻辑

### 时机
在 per-KB 召回 + 跨库 RRF 融合之后，rerank 之前（或在返回前统一填充）。

### 实现
```python
# 批量预加载 kb_id → kb_name 映射
rows = await self._kb_repo.pool.fetch(
    "SELECT id, name FROM knowledge_bases WHERE id = ANY($1)", kb_ids
)
kb_names = {row["id"]: row["name"] for row in rows}

# 逐 chunk 填充 kb_name
for hit in hits:
    hit.kb_name = kb_names.get(hit.kb_id, hit.kb_id[:8])
```

### 边界
- kb_name 不在 DB 中 → 回退为 `kb_id[:8]`（前缀展示）
- kb_id 列表为空 → `kb_names` 为空 dict，全部回退

## 参考
- `KnowledgeBase` 模型在 `models.py` 中定义，有 `name` 字段
- `self._kb_repo` 是 `KnowledgeBaseRepository` 实例，有 `pool` 属性用于 `asyncpg` 查询
- 老代码可能用 `getattr(kb, "name", "")` 获取 name

## 注意
- **不修改 `retrieve_use_case.py` 的检索管线部分**（那是 1.2/1.3 的职责）— 仅添加 kb_name 填充
- 子任务 A 和 B 可以分开提交，或一个提交包含两个改动
- 确保 `models.py` 的改动向后兼容：默认值 + 仅追加字段

## 验证
- `SearchHit(...)` 构造时不传 `kb_name` 仍可工作（取默认 `""`）
- 后端 API 序列化时输出 `kb_name`（task 2.3 做 `_serialize_hit` 适配）
- kb_name 填充逻辑正确：DB 有 → 取 name；无 → 取 `kb_id[:8]`
