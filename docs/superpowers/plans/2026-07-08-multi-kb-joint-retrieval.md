---
change: multi-kb-joint-retrieval
design-doc: docs/superpowers/specs/2026-07-08-multi-kb-joint-retrieval-design.md
base-ref: 68ac839940a4127fe71adc33d04015937e675af8
archived-with: 2026-07-08-multi-kb-joint-retrieval
---

# 多知识库联合检索 — 实施计划

## 概述

将 `RetrieveUseCase.execute` 从"向量跨库单次查询 + BM25 仅查 kb_ids[0]"重构为"per-KB 并行召回 + 两阶段 RRF 融合"。涉及后端核心 ~100 行重构、Plan 配额联动、前端检索页 Checkbox 改造、eval 适配。

## 依赖关系

```
Phase 1: 后端核心 ──────────┐
  ├─ 1.1 cross_kb_rrf_fuse  │
  ├─ 1.2 RetrieveUseCase    │
  └─ 1.3 SearchHit + kb_name│
                             ↓
Phase 2: Plan + 响应 ───────┐
  ├─ 2.1 plan_presets       │
  ├─ 2.2 router 校验         │
  └─ 2.3 响应扩展            │
                             ↓
Phase 3: 前端 ───────────────┐    Phase 4: Eval ─────┐
  ├─ 3.0 TypeScript 类型更新  │      ├─ 4.1 dataset    │
  ├─ 3.1 Checkbox 多选       │      ├─ 4.2 scripts    │
  ├─ 3.2 KB Badge            │      └─ 4.3 golden     │
  └─ 3.3 摘要区               │                        │
Phase 5: 测试 ───────────────────────────────────────┐
  ├─ 5.1 单元测试                                     │
  ├─ 5.2 E2E 测试                                     │
  └─ 5.3 eval regression                              │
```

archived-with: 2026-07-08-multi-kb-joint-retrieval
---

## Phase 1: 后端核心检索管道

### 1.1 新增 `cross_kb_rrf_fuse` 函数

**文件**: `src/ragnexus/domain/retrieval/fusion.py`

**实现要点**:
- 输入: `list[list[SearchHit]]` — 每组是一个 KB 的库内 RRF 后 rank-ordered hits
- 算法: `rrf_score = Σ 1/(k + rank_in_kb)`，rank 从 1 开始
- 若同一 chunk_id 出现在多个 KB 中，累加各库 RRF 贡献
- 按 rrf_score 降序排序返回
- 复用现有 `_merge_metadata` 处理跨库重复 chunk 的 metadata 合并

```python
def cross_kb_rrf_fuse(
    kb_hits_groups: list[list[SearchHit]],
    k: int = 60,
) -> list[SearchHit]:
    """跨库 RRF 融合：基于 per-KB rank 重新计算分数并合并。"""
```

**验证**: 单元测试覆盖多组输入、单组退化（等价于不排序）、空组、rank 均衡性

### 1.2 重构 `RetrieveUseCase._retrieve_per_kb`

**文件**: `src/ragnexus/application/retrieve_use_case.py`

**新增方法**:
```python
async def _retrieve_per_kb(
    self, kb_id: str, search_vector, original_query: str,
    per_kb_top_k: int, rrf_k: int, use_vector: bool, use_bm25: bool,
) -> list[SearchHit]:
    """单库召回：vector + BM25 → 库内 RRF，返回 rank-ordered hits。"""
```

内部流程:
1. `self._store.search_by_vector(search_vector, per_kb_top_k, [kb_id])` — 单库向量
2. `self._keyword_store.search_by_keyword(kb_id, original_query, per_kb_top_k)` — 单库 BM25
3. `rrf_fuse(vec_hits, kw_hits, k=rrf_k)` — 库内 RRF
4. 对每条 hit 标记分数（`_vector_score` / `_bm25_score` 写入 metadata）

### 1.3 重构 `RetrieveUseCase.execute` 主流程

**改动**: 将第 184-240 行（并行召回 + RRF 融合）替换为：

```python
# 3c. per-KB 并行召回
per_kb_top_k = max(top_k, _vector_top_k, _bm25_top_k, 10)
kb_tasks = [
    self._retrieve_per_kb(kb_id, search_vector, original_query,
                          per_kb_top_k, rrf_k, use_vector, use_bm25)
    for kb_id in kb_ids
]
kb_groups = await asyncio.gather(*kb_tasks, return_exceptions=True)
# 过滤异常 KB
valid_groups = [g for g in kb_groups if not isinstance(g, Exception)]

# 3d. 跨库 RRF 融合
hits = cross_kb_rrf_fuse(valid_groups, k=rrf_k)
```
保留原有: query 处理、embedding、计时代码、降级逻辑、rerank、日志

### 1.4 SearchHit 扩展 + kb_name 预加载

**SearchHit** (`src/ragnexus/domain/models.py`):
```python
@dataclass
class SearchHit:
    kb_name: str = ""  # 新增
```

**kb_name 预加载**（在 per-KB 召回后，跨库 RRF 融合后）:
```python
rows = await self._kb_repo.pool.fetch(
    "SELECT id, name FROM knowledge_bases WHERE id = ANY($1)", kb_ids
)
kb_names = {row["id"]: row["name"] for row in rows}
for hit in hits:
    hit.kb_name = kb_names.get(hit.kb_id, hit.kb_id[:8])
```

### 1.5 多库词表合并

在 query 处理前，批量加载所有 KB 的 settings JSON，合并 synonyms 列表去重：
```python
all_synonyms = []
for kb_id in kb_ids:
    kb = await self._kb_repo.get(kb_id)
    settings = json.loads(getattr(kb, "settings", "{}") or "{}")
    all_synonyms.extend(settings.get("synonyms", []))
# 去重
synonyms = list({s["term"]: s for s in all_synonyms}.values()) if all_synonyms else None
```

### 1.6 多库改写上下文

LLM 改写时 `kb_context` 改为列表：
```python
kb_contexts = []
for kb_id in kb_ids:
    kb = await self._kb_repo.get(kb_id)
    kb_contexts.append({"name": kb.name, "description": getattr(kb, "description", "")})
```

### 1.7 per-KB 降级处理

`_retrieve_per_kb` 内部：
- BM25 失败 → 降级为纯向量，记录 `degraded_kb_id` + reason
- 向量也失败 → 返回空列表（该 KB 被跳过）
- `execute` 中 `asyncio.gather(return_exceptions=True)` + 过滤 Exception

archived-with: 2026-07-08-multi-kb-joint-retrieval
---

## Phase 2: Plan 配额联动 + 响应扩展

### 2.1 plan_presets 新增字段

**文件**: `src/ragnexus/tenant/plan_presets.py`

在 `"limits"` 下增加:
```python
"max_kb_per_retrieve": 1,  # free
"max_kb_per_retrieve": 3,  # standard
"max_kb_per_retrieve": 5,  # pro
```

### 2.2 router 入口校验

**文件**: `src/ragnexus/adapters/http/retrieve_router.py`

在 Step 1（resolve_plan）之后插入:
```python
max_kb = plan_ctx.limits.get("max_kb_per_retrieve", 5)
if len(req.kb_ids) > max_kb:
    raise AppError(
        ErrorCode.FEATURE_NOT_ALLOWED,
        f"当前套餐最多支持 {max_kb} 个库联合检索",
    )
```

### 2.3 响应体扩展

**文件**: `src/ragnexus/adapters/http/retrieve_router.py`

响应 data 根级增加 `kb_ids`:
```python
"data": {
    "query": req.query,
    "kb_ids": req.kb_ids,  # 新增
    "hits": [...],
    ...
}
```

meta 增加多库元信息:
```python
"multi_kb": len(req.kb_ids) > 1,
"kb_count": len(req.kb_ids),
"per_kb_top_k": per_kb_top_k,
"fusion": "rrf",
"rrf_k": req.rrf_k,
```

`_serialize_hit` 输出 `kb_name`。

archived-with: 2026-07-08-multi-kb-joint-retrieval
---

## Phase 3: 前端检索页改造

### 3.0 TypeScript 类型更新（前置）

- `RetrieveRequest` 类型确认 `kb_ids: string[]`（当前已有，确认无需改）
- `RetrieveResponse` 新增 `data.kb_ids` 和 `meta.multi_kb`/`fusion`/`kb_count` 字段
- `RetrieveHit` 新增 `kb_name: string` 字段

### 3.1 Checkbox 多选

- 调用 `GET /v1/knowledge-bases/tree` 获取 tenant 下 KB 列表
- 渲染 Checkbox 列表，每个 Checkbox 显示 KB 名称 + ID
- 至少勾选一个才允许提交，否则 toast 提示
- 列表页「去检索」跳转时，URL `kb_id` 对应库默认勾选
- 勾选多个时请求 body 传 `kb_ids: [...]`

### 3.2 来源库 Badge

每条 `RetrieveHit` 的卡片上增加 Badge：
- 显示 `kb_name`（或 `kb_id` 前 8 位作为回退）
- 不同库用不同底色区分（可用 `kb_id` hash 取色）

### 3.3 运行摘要区

检索结果顶部展示: `联查 N 个库 | 融合方式: rrf | 耗时 XXXms`

### 3.4 plan 限制提示

`20013` 错误时，在选择框旁展示: "当前套餐最多支持 N 个库联合检索"

archived-with: 2026-07-08-multi-kb-joint-retrieval
---

## Phase 4: Eval & 脚本适配

### 4.1 eval dataset 扩展

`cases` 记录支持 `kb_ids` 字段，兼容旧 `kb_id`。

### 4.2 run_retrieval_eval.py 适配

读 case 时: `kb_ids = case.get("kb_ids") or [case["kb_id"]]`

### 4.3 新增跨库 golden cases

`eval/datasets/multi_kb_cases.json`，2-3 条必须跨库才能答全的测例。

### 4.4 Langfuse 导出适配

`export_eval_cases_from_langfuse.py`: 读 trace metadata 优先取 `kb_ids`，回退 `kb_id`。

### 4.5 文档更新

- `README` retrieve 小节增加 `kb_ids` curl 示例
- `docs/tenant-onboarding.md` 增加 `max_kb_per_retrieve` 说明

archived-with: 2026-07-08-multi-kb-joint-retrieval
---

## Phase 5: 测试

### 5.1 单元测试

**文件**: `tests/unit/domain/test_fusion.py`
- `test_cross_kb_rrf_fuse_two_groups`: 两组各 5 条，验证 rank 均衡
- `test_cross_kb_rrf_fuse_single_group`: 单组退化
- `test_cross_kb_rrf_fuse_empty_group`: 空组过滤
- `test_cross_kb_rrf_fuse_duplicate_chunk`: 跨库重复 chunk RRF 累加

**文件**: `tests/unit/application/test_retrieve_use_case.py`
- Mock `_retrieve_per_kb` 返回两组 hits，验证跨库 RRF 融合
- 单库调用走统一路径，验证结果等价

**文件**: `tests/unit/tenant/test_plan_presets.py`
- 验证 free/standard/pro 的 `max_kb_per_retrieve` 值

### 5.2 E2E 测试

**文件**: `tests/e2e/test_multi_kb_retrieve.py`（新增）
- 单库向后兼容（旧 curl 零破坏）
- 双库跨域 query → 两库 chunk 均出现
- free 租户 2 库 → `20013`
- 跨 tenant 库 ID → `NOT_FOUND`
- 不存在的库 ID → 整体失败
- 配额计数：双库仅 +1

### 5.3 Eval regression

- 原 `ecommerce_retrieval.json` 跑单库 eval，分数与 baseline 无明显下降
- `multi_kb_cases.json` 跨库 eval，`context_recall` 明显高于单库

archived-with: 2026-07-08-multi-kb-joint-retrieval
---

## 实施顺序

1. **1.1** → **1.2** → **1.3** → **1.4**（后端核心，有依赖）
2. **2.1** → **2.2** → **2.3**（Plan + 响应，依赖 1.x 完成）
3. **3.1-3.4**（前端，可与 Phase 2 并行）
4. **4.1-4.5**（Eval，可与 Phase 3 并行）
5. **5.1-5.3**（测试，依赖前四个 Phase）

估计总改动量: ~600 行（含测试）
