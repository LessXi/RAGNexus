---
comet_change: multi-kb-joint-retrieval
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-08-multi-kb-joint-retrieval
status: final
---

# 多知识库联合检索 — 技术设计

> 基于飞书需求文档（"为什么需要多知识库联合检索"、"多库并行召回与RRF融合提示词"、"调试台与测评适配提示词"、"测试验收"）与融合分析的技术设计。

## 1. 背景与当前状态

当前 `RetrieveUseCase.execute` 已接受 `kb_ids: list[str]`，但检索执行体存在结构性缺口：
- 向量搜索跨所有库一次查询（pgvector `WHERE kb_id = ANY($1)`），不同库的 embedding 分布混排
- BM25 仅搜索 `kb_ids[0]`（`retrieve_use_case.py:193`），其他库关键词结果缺失
- 单次 RRF 融合向量+BM25，无跨库 rank 考量

本设计将检索管道从"跨库单次查询"重构为"per-KB 并行召回 + 两阶段 RRF"。

## 2. 目标与非目标

**目标**：
- per-KB 并行召回（每个库独立 vector + BM25 → 库内 RRF）
- 跨库 RRF 融合，基于 per-KB rank 而非 raw score
- Plan 分级管控多库上限
- 响应 chunk 携带 `kb_id`/`kb_name`，meta 增加多库元信息
- 前端 Checkbox 多选 + 来源库 Badge
- 单库路径向后兼容

**非目标**：不改 chunking/embedding/parser；不做 KB 权重；不改上传/列表页。

## 3. 架构设计

### 3.1 检索流程

```
POST /v1/rag:retrieve { kb_ids, query, profile }
  │
  ├─ Plan 校验: len(kb_ids) ≤ plan.max_kb_per_retrieve
  ├─ KB 存在性校验 + 租户归属校验
  ├─ Query 处理一次（词表扩展 / LLM 改写）→ search_query
  ├─ Embedding 一次 → search_vector
  │
  ├─ asyncio.gather ──────────────────────────────────┐
  │   ├─ KB_A: vector + BM25 → 库内 RRF → top N      │
  │   ├─ KB_B: vector + BM25 → 库内 RRF → top N      │
  │   └─ KB_C: vector + BM25 → 库内 RRF → top N      │
  │   per_kb_top_k = max(top_k, vector_top_k, 10)      │
  └────────────────────────────────────────────────────┘
  │
  ├─ cross_kb_rrf_fuse(kb_groups, k=60) → top_k
  ├─ 预加载 kb_id → kb_name 映射 → 填充 SearchHit
  ├─ Rerank（若开启）→ 融合后统一执行一次
  │
  └─ 响应: data.kb_ids + hits[].kb_id/kb_name
           + meta.multi_kb/fusion/kb_count/per_kb_top_k/rrf_k
```

### 3.2 两阶段 RRF 原理

**库内 RRF**（已有）：`rrf_score = Σ 1/(k + rank_in_source)`，融合 vector 和 BM25 两路。

**跨库 RRF**（新增）：`rrf_score = Σ 1/(k + rank_in_kb)`，融合多个 KB 的 rank-ordered 候选。
选择 RRF 而非直接比较 raw score 的原因：向量 score 和 BM25 score 在不同 KB 间不可直接比较（不同 chunking 策略导致 embedding 分布不同；BM25 的 IDF 是索引内归一化）。RRF 只看 rank，天然跨源可比。

### 3.3 多库词表合并

词表扩展阶段 SHALL 合并所有 KB 的 synonyms 列表（批量加载 settings 去重），而非仅使用 `kb_ids[0]` 的词表。LLM 改写的 `kb_context` SHALL 包含所有 KB 的 name + description 列表，让 LLM 知道搜索范围横跨多个知识域。

### 3.4 per-KB 降级处理

某 KB 的 BM25 失败时 SHALL 降级为纯向量召回，不影响其他 KB。向量也失败时 SHALL 跳过该 KB（返回空列表）。跨库 RRF 仅融合成功返回的候选。降级信息 SHALL 记录在日志中。

### 3.5 单库路径

单库和多库统一走 per-KB 路径。当 `len(kb_ids) == 1` 时：
- `asyncio.gather` 只有一个 task
- 库内 RRF 后跨库 RRF 退化为恒等映射
- 行为应与改前完全一致

## 4. 关键模块改动

### 4.1 `domain/retrieval/fusion.py` — 新增 `cross_kb_rrf_fuse`

```python
def cross_kb_rrf_fuse(
    kb_hits_groups: list[list[SearchHit]],  # 每组是一个 KB 的 rank-ordered hits
    k: int = 60,
) -> list[SearchHit]:
    """跨库 RRF 融合：基于 per-KB rank 重新计算分数并合并。
    
    同一 chunk_id 命中多个 KB（未来可能）时累加各库 RRF 贡献。
    """
```

### 4.2 `application/retrieve_use_case.py` — 重构 `execute`

```python
async def _retrieve_per_kb(
    self, kb_id: str, search_vector, original_query,
    per_kb_top_k, rrf_k
) -> list[SearchHit]:
    """单库召回：vector + BM25 → 库内 RRF，返回 rank-ordered hits。"""

async def execute(self, ...):
    # 1. 校验（不变）
    # 2. Query 处理 + Embedding（不变，只做一次）
    # 3. asyncio.gather 各 KB 并行召回
    tasks = [self._retrieve_per_kb(kb_id, ...) for kb_id in kb_ids]
    kb_groups = await asyncio.gather(*tasks)
    # 4. 跨库 RRF
    hits = cross_kb_rrf_fuse(kb_groups, k=rrf_k)
    # 5. 填充 kb_name（预加载映射）
    # 6. Rerank + 返回
```

### 4.3 `tenant/plan_presets.py` — 新增字段

```python
"limits": {
    "max_kb_per_retrieve": 1,  # free
    "max_kb_per_retrieve": 3,  # standard
    "max_kb_per_retrieve": 5,  # pro
}
```

### 4.4 前端检索页

- 知识库列表改为 Checkbox 多选（数据源 `GET /v1/knowledge-bases/tree`）
- 每条 chunk 增加来源库 Badge（取 `kb_name`，不同颜色区分）
- 运行摘要展示联查库数和融合方式
- `20013` 错误时展示套餐提示

## 5. 数据流

```
Request { kb_ids, query }
  → TenantContext.plan.limits.max_kb_per_retrieve（校验）
  → QueryPipeline.process（一次）
  → Embedder.embed([search_query])（一次）
  → [VectorStore.search_by_vector + KeywordStore.search_by_keyword] × N（并行）
  → rrf_fuse × N（库内）
  → cross_kb_rrf_fuse（跨库）
  → KB 表批量查询 kb_name
  → Reranker.rerank（一次）
  → Response { kb_ids, hits[].kb_id/kb_name, meta.multi_kb/... }
```

## 6. 错误处理

| 场景 | 错误码 | 说明 |
|------|--------|------|
| `kb_ids` 超 plan 上限 | `20013` | `FEATURE_NOT_ALLOWED` |
| 部分 KB 不属于当前 tenant | `NOT_FOUND` | `KNOWLEDGE_BASE_NOT_FOUND`，错误 context 含具体 `missing_kb_id`；选择 404 而非 403 是为了不泄露其他 tenant 的 KB 存在性信息 |
| KB 不存在 | `NOT_FOUND` | 错误 context 含具体 ID |
| `kb_ids` 超硬上限 5 | `PARAM_ERROR` | |

## 7. 测试策略

### 单元测试
- `test_cross_kb_rrf_fuse`：多组输入 rank 均衡、单组退化、空组、重复 chunk_id 累加
- `test_retrieve_per_kb`：单库 vector+BM25 并行、BM25 降级路径
- `test_plan_max_kb_per_retrieve`：三档预设值验证

### E2E 测试
- 单库向后兼容（旧 curl 零破坏）
- 双库跨域 query → 两库 chunk 均出现在结果中
- free 租户 2 库 → 20013
- 跨 tenant 库 ID → NOT_FOUND
- 配额计数：双库检索仅 +1
- 检索日志 `kb_ids` JSONB 字段正确

### Eval 回归
- 原 `ecommerce_retrieval.json` 单库分数与 baseline 无明显下降
- 新增 `multi_kb_cases.json` 跨库 golden case，`context_recall` 明显高于单库

## 8. 部署与回滚

- 后端先上（API 向后兼容），前端随后
- 单 `kb_id` 路径不变，回滚无风险
- 无 schema 迁移（`kb_ids` JSONB 已存在）
