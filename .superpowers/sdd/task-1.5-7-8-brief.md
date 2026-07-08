# Task 1.5+1.7+1.8: execute 方法补充增强

三个子任务都是对 `RetrieveUseCase.execute` 方法的小改动，合并在同一任务中避免冲突。

## 子任务 A (1.5): kb_name 预加载与填充

在跨库 RRF 融合后、rerank 前，批量预加载 kb_id→kb_name 并填充每条 hit。

```python
# 批量预加载
rows = await self._kb_repo.pool.fetch(
    "SELECT id, name FROM knowledge_bases WHERE id = ANY($1)", kb_ids
)
kb_names = {row["id"]: row["name"] for row in rows}

# 填充（hits 已由 cross_kb_rrf_fuse 产生）
for hit in hits:
    hit.kb_name = kb_names.get(hit.kb_id, hit.kb_id[:8])
```

## 子任务 B (1.7): 多库词表合并

在 query 处理前，批量加载所有 KB 的 settings JSON，合并 synonyms 去重。

```python
import json
all_synonyms = []
for kb_id in kb_ids:
    kb = await self._kb_repo.get(kb_id)
    if kb is None:
        continue
    settings_raw = getattr(kb, "settings", "{}") or "{}"
    settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
    all_synonyms.extend(settings.get("synonyms", []))
synonyms = list({s["term"]: s for s in all_synonyms}.values()) if all_synonyms else None
```

## 子任务 C (1.8): 多库改写上下文

LLM 改写时，将 kb_context 改为所有 KB 的描述列表。

```python
kb_contexts = []
for kb_id in kb_ids:
    kb = await self._kb_repo.get(kb_id)
    if kb:
        kb_contexts.append({"name": kb.name, "description": getattr(kb, "description", "")})
```

## 注意
- 所有修改在 execute 方法内，不新建方法
- asyncpg JSONB 字段返回 str，需要 `json.loads()`
- 子任务 B 的 synonyms 合并逻辑参考现有代码中的 synonyms 处理位置
- 边界: KB 不存在/settings 为空/synonyms 缺失 → 跳过不阻塞

## 验证
- kb_name 正常填充 + 回退到 kb_id[:8]
- 多库 synonyms 去重正确
- kb_contexts 列表构造正确
