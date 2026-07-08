# Task 1.5 Report: kb_name 预加载与填充

## 状态
✅ 完成 | commit `c3f3728`

## 改动摘要

### 实现 (`src/ragnexus/application/retrieve_use_case.py`)
在 `execute` 方法中，`cross_kb_rrf_fuse` 之后、`rerank` 之前，插入了 7 行 kb_name 填充逻辑：

```python
# 3d.5 批量预加载 kb_name（跨库 RRF 融合后、rerank 前）
rows = await self._kb_repo.pool.fetch(
    "SELECT id, name FROM knowledge_bases WHERE id = ANY($1)", kb_ids
)
kb_names_map: dict[str, str] = {row["id"]: row["name"] for row in rows}
for hit in hits:
    hit.kb_name = kb_names_map.get(hit.kb_id, hit.kb_id[:8])
```

- **位置**: 跨库 RRF 融合后（line 230）、rerank 前（line 241），满足 "rerank 可能需要 kb_name" 的约束
- **批量查询**: 一次 SQL 查询所有 `kb_ids`，避免 N+1
- **回退策略**: DB 无记录 → `kb_id[:8]`；`kb_ids` 为空 → 空 map，全部回退

### 测试 (`tests/unit/application/test_retrieve_use_case.py`)
新增 2 个测试用例：

| 测试 | 覆盖 |
|------|------|
| `test_kb_name_populated` | 3 个 KB 正常填充，验证 `pool.fetch` 被调用且 kb_name 正确 |
| `test_kb_name_fallback` | DB 中无对应 kb_id → 回退为 `kb_id[:8]` |

## TDD 流程
1. **RED**: 编写 2 个测试 → 确认失败（`fetch` 未调用 / `kb_name` 为空字符串）
2. **GREEN**: 插入 7 行实现 → 2 测试通过
3. **REFACTOR**: N/A（代码简洁，无需重构）
4. **REGRESSION**: 全文件 16 测试全部通过

## 边界覆盖
- ✅ 正常路径: `kb_name` 正确填充
- ✅ 回退路径: 不存在的 `kb_id` → `kb_id[:8]`
- ✅ 空 hits: `cross_kb_rrf_fuse` 返回空列表 → for 循环无操作
- ✅ 空 kb_ids: 参数校验阶段即抛出 `PARAM_ERROR`
