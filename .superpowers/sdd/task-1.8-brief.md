# Task 1.8: 多库改写上下文

## 文件
`src/ragnexus/application/retrieve_use_case.py` — `execute` 方法中，在 LLM 改写前，将 `kb_context` 从单库描述扩展为所有 KB 的描述列表。

## 实现要点

### 当前代码
LLM 改写时可能使用单个 KB 的 name 作为 context。需要改为所有 KB 的列表：
```python
# 旧: 单个 KB context
# kb_context = kb.name + ": " + kb.description

# 新: 所有 KB context
kb_contexts = []
for kb_id in kb_ids:
    kb = await self._kb_repo.get(kb_id)
    if kb:
        kb_contexts.append({
            "name": kb.name,
            "description": getattr(kb, "description", ""),
        })
```

### 传递给 LLM
`kb_contexts` 列表传给 LLM 改写 prompt，让 LLM 理解所有参与检索的 KB 的领域范围。

### 边界
- 某些 KB 加载失败 → 跳过，不阻塞
- 空列表 → 不改写或使用默认上下文

### 位置
- 在 query 处理流程中，LLM 改写之前
- 找到当前的 kb_context 构建代码并替换

### 参考
- `self._kb_repo.get(kb_id)` 返回 `KnowledgeBase | None`
- `KnowledgeBase` 有 `name` 和 `description` 字段
