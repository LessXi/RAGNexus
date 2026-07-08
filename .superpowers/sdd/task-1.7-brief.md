# Task 1.7: 多库词表合并

## 文件
`src/ragnexus/application/retrieve_use_case.py` — `execute` 方法中，在 query 处理阶段前，批量加载所有 KB 的 settings 并合并 synonyms。

## 实现要点

### 批量加载
```python
# 在 query 处理前，批量加载所有 KB settings
all_synonyms = []
for kb_id in kb_ids:
    kb = await self._kb_repo.get(kb_id)
    if kb is None:
        continue
    # settings 可能是 JSONB 字段，asyncpg 返回 str
    settings_raw = getattr(kb, "settings", "{}") or "{}"
    settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
    all_synonyms.extend(settings.get("synonyms", []))
```

### 去重合并
```python
import json  # 确保导入
synonyms = None
if all_synonyms:
    # 按 term 去重
    synonyms = list({s["term"]: s for s in all_synonyms}.values())
```

### 使用
合并后的 `synonyms` 传给 QueryPipeline（替换原来的单库 synonyms）。

### 边界
- 某些 KB 没有 settings → 跳过
- settings 中没有 synonyms → 跳过
- JSON 解析失败 → 跳过该 KB，记录 warning

### 位置
- 在 embedding 之前的 query 处理阶段
- 找到当前的 synonyms 加载代码并扩展为多库

### 参考
- asyncpg JSONB 返回 Python str，需要 `json.loads()`
- `KnowledgeBase.settings` 字段的读取方式参考现有代码
- `self._kb_repo.get(kb_id)` 返回 `KnowledgeBase | None`
