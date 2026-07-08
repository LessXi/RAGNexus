# 多知识库联合检索 — 第一性原理融合分析

> 基于飞书四篇需求文档与当前代码库（2026-07-08）的深度比对。

---

## 一、需求核心

让 `/v1/rag:retrieve` 原生支持传入多个 `kb_ids`，中台并行查询各库，跨库 RRF 融合排序后统一返回。调用方感知到的仍是一次检索调用，chunk 带上来源库信息。

**本质**：从"单库检索"扩展到"多库联合检索"，在召回环节做文章，其他管道（query 改写、rerank、日志）基本复用。

---

## 二、当前实现 vs 设计文档：结构级比对

### 2.1 当前代码库已有的多库基础

| 组件 | 状态 | 细节 |
|------|------|------|
| API 契约 `kb_ids: list[str]` | ✅ 已有 | `_RetrieveRequest.kb_ids` 已是 list，`kb_id` 字段已不存在 |
| `RetrieveUseCase.execute(kb_ids=...)` | ✅ 已有 | 签名接受 `kb_ids: list[str]` |
| 租户归属校验 | ✅ 已有 | `validate_kb_ownership()` 用 `SELECT COUNT(*) … WHERE id = ANY($1) AND tenant_id = $2` |
| KB 存在性校验 | ✅ 已有 | 逐个 `kb_repo.exists(kb_id)` |
| 5-KB 硬上限 | ✅ 已有 | `len(kb_ids) > 5` → `PARAM_ERROR` |
| `retrieval_logs.kb_ids` JSONB | ✅ 已有 | `PgRetrieveLogRepository` INSERT 含 `kb_ids` |
| Langfuse trace `kb_ids` metadata | ✅ 已有 | router 第 157 行写入 `"kb_ids": req.kb_ids` |
| 响应 chunk 带 `kb_id` | ✅ 已有 | `_serialize_hit` 输出 `"kb_id": h.kb_id` |
| 前端 `RetrieveRequest.kb_ids` | ✅ 已有 | TypeScript 类型已是 `kb_ids: string[]` |

### 2.2 当前实现的结构性问题

```
当前检索流程（RetrieveUseCase.execute）:
  query → 改写 → embedding → ┌─ vector: search_by_vector(embedding, top_k, kb_ids)  ← 跨所有库
                              │
                              └─ BM25: search_by_keyword(kb_ids[0], query, top_k)  ← 🔴 只查第一个库！
                              ↓
                          rrf_fuse(vec_hits, kw_hits)  ← 单次 RRF，不是跨库 RRF
                              ↓
                          rerank → 返回
```

**三个根本性问题**：

1. **BM25 只查 `kb_ids[0]`**（`retrieve_use_case.py:193-194`）。多库场景下，其他库的关键词匹配结果完全缺失，融合池里只有向量结果代表它们。

2. **向量搜索是跨库单次查询**。pgvector 的 `WHERE kb_id = ANY($1)` 是把所有库的向量混在一起按余弦距离排序。不同库可能有不同的 chunking 策略和 embedding 分布，混排的 score 并不保证跨库公平。

3. **没有跨库 RRF 融合**。当前 `rrf_fuse` 融合的是向量路 + BM25 路（同一 query 的两路），而不是多个知识库的各自 top 候选。库 A 的 5 条全排前面时，库 B 的相关结果就被挤掉了——这正是需求文档指出的问题。

### 2.3 设计文档要求的架构

```
设计文档要求的流程:
  query → 改写 → embedding
    ↓
  asyncio.gather 对各 KB 并行:
    ├─ KB_A: vector + BM25 → per-KB RRF → top per_kb_top_k
    ├─ KB_B: vector + BM25 → per-KB RRF → top per_kb_top_k
    └─ KB_C: vector + BM25 → per-KB RRF → top per_kb_top_k
    ↓
  跨库 RRF 融合（基于各库 rank，非 raw score）
    ↓
  rerank（对融合后候选统一执行一次）
    ↓
  返回 top_k
```

---

## 三、第一性原理分析

### 3.1 为什么需要 per-KB 隔离

**向量 score 不可跨库比较**。pgvector 用余弦距离，但不同 KB 的 chunk embedding 分布可能不同（chunk 大小、内容类型、语言分布影响 embedding 的模长统计）。库 A 的 score=0.85 和库 B 的 score=0.85 不代表同等相关性。

**BM25 score 不可跨库比较**。BM25 的 IDF 分量依赖集合统计——"退款"在 100 篇电商文档里的 IDF 和在 1000 篇综合文档里的 IDF 不同。Elasticsearch 的 `_score` 是索引内归一化的，跨索引不可比。

**RRF 只看 rank 不看 score**，天然解决跨源比较问题。rank 1 = 1/(60+1)，rank 2 = 1/(60+2)，与原始分值无关。

**结论**：per-KB 独立召回 + per-KB 内 rank + 跨库 RRF 是从第一性原理出发的正确架构。

### 3.2 为什么 per-KB hybrid 优于"向量跨库 + BM25 单库"

当前做法 `search_by_vector(embedding, top_k, kb_ids)` + `search_by_keyword(kb_ids[0], ...)` 本质上是不对称的——BM25 只覆盖第一个库，向量覆盖所有库但 score 不可比。融合结果隐含 bias：第一个库的关键词匹配会排得更靠前。

### 3.3 并行策略的延迟考量

需求文档说"查三个库的延迟和查一个库接近"。从第一性原理验证：

- **asyncio.gather 并行**：3 个 KB 同时发起 vector+BM25，延迟 ≈ max(单库延迟)，而非 sum
- **embedding 只算一次**：`embed([search_query])` 一个向量，各库复用
- **rerank 只跑一次**：融合后的 top_k 候选统一 rerank，不分库分别跑

墙钟时间瓶颈在：最慢的那个 KB 的 vector 搜索（pgvector）+ 最慢的那个 KB 的 BM25（ES），两者在同 KB 内可以再并行。实际延迟与单库接近，这个判断成立。

---

## 四、融合方案：具体改动清单

按"最小破坏、最大增益"原则，列出需要的改动和优先级。

### 🔴 P0 — 核心检索管道改造（后端）

#### 4.1 重构 `RetrieveUseCase.execute` — per-KB 并行召回

**改动**：将当前的"向量跨库 + BM25 单库 → 单次 RRF"改为：

```
for each kb_id in kb_ids (asyncio.gather):
    1. vector: search_by_vector(embedding, per_kb_top_k, [kb_id])  ← 单库
    2. BM25: search_by_keyword(kb_id, query, per_kb_top_k)          ← 单库
    3. per-KB RRF: rrf_fuse(vec_hits, kw_hits, k=rrf_k)            ← 库内融合
    → 返回 per_kb_top_k 条（带库内 rank）
↓
跨库 RRF: 基于 per-KB rank 再次融合 → top_k
```

**关键参数**：`per_kb_top_k = max(top_k, vector_top_k, 10)`。每个库先多捞一点，保证融合候选池充足。

**新函数**：在 `src/ragnexus/domain/retrieval/fusion.py` 新增 `cross_kb_rrf_fuse(kb_hits_groups, k=60) -> list[SearchHit]`，逻辑与 `rrf_fuse` 类似但输入是多组（每组是一个 KB 的 rank-ordered hits）。

#### 4.2 新增 `max_kb_per_retrieve` 字段到 Plan 预设

**文件**：`src/ragnexus/tenant/plan_presets.py`

```python
"free":     {"limits": {..., "max_kb_per_retrieve": 1}},   # 仅单库
"standard": {"limits": {..., "max_kb_per_retrieve": 3}},   # 覆盖双库场景
"pro":      {"limits": {..., "max_kb_per_retrieve": 5}},   # 与 MULTI_KB_MAX 一致
```

**校验位置**：`retrieve_router.py` 的 Step 1-2 之间，校验 `len(req.kb_ids) <= plan_ctx.limits.max_kb_per_retrieve`，超限返回 `20013`。

**注意**：当前硬编码的 `MULTI_KB_MAX=5`（`retrieve_use_case.py:99`）保留为硬上限，plan 的 `max_kb_per_retrieve` 在其之下。

#### 4.3 chunk 增加 `kb_name` 字段

在 `RetrieveUseCase.execute` 中，跨库 RRF 融合后，对每条 `SearchHit` 填充 `kb_name`（通过查 KB 表或预加载 kb_id→name 映射）。

**SearchHit 扩展**：在 `SearchHit` dataclass 中新增 `kb_name: str = ""` 字段。

#### 4.4 响应体扩展

在 `retrieve_router.py` 的响应 data 中增加 `kb_ids` 字段（设计文档要求的显式返回），`meta` 中增加多库信息：

```json
{
  "data": {
    "kb_ids": ["kb_ecommerce", "kb_customer_service"],
    "hits": [...],
    "meta": {
      ...现有字段,
      "multi_kb": true,
      "kb_count": 2,
      "per_kb_top_k": 10,
      "fusion": "rrf",
      "rrf_k": 60
    }
  }
}
```

#### 4.5 配额计数确认

**当前已正确**：`rate_limiter.record_retrieve_success(tenant_id)` 在 router 的 finally 块只调用一次，不随库数倍增。日检索配额只计 1 次——设计文档要求与此一致，无需改动。

---

### 🟡 P1 — 前端 & 调试台改造

#### 4.6 检索页 KB 多选

**文件**：`admin/src/pages/RetrievePage.tsx`（或对应组件）

- 当前是单 `kb_id` 文本输入 → 改为 Checkbox 多选列表
- 数据源：`GET /v1/knowledge-bases/tree`
- 至少勾选一个，否则提示
- 勾选多个时传 `kb_ids: [...]`

#### 4.7 chunk 来源库 Badge

每条 `RetrieveHit` 已有 `kb_id`，补充 `kb_name`（后端返回后），在卡片上显示来源库 Badge（不同颜色区分）。

#### 4.8 运行摘要区

增加"联查 N 个库 | 融合方式: rrf"等信息（从 `meta` 读取）。

#### 4.9 plan 限制提示

`20013` 错误时展示「当前套餐最多支持 N 个库联合检索」。

---

### 🟢 P2 — 测评 & 周边适配

#### 4.10 eval dataset 扩展

`cases` 记录支持 `kb_ids` 字段（兼容旧 `kb_id`）。

#### 4.11 `run_retrieval_eval.py` 适配

读 case 时优先取 `kb_ids`，回退取 `kb_id`，请求 body 传 `kb_ids`。

#### 4.12 新增跨库 golden case

`eval/datasets/multi_kb_cases.json`：2-3 条必须跨库才能答全的测例。

#### 4.13 Langfuse 导出脚本适配

`export_eval_cases_from_langfuse.py`：读 trace metadata 时优先取 `kb_ids`，回退取 `kb_id`。

---

## 五、不改的范围

| 组件 | 原因 |
|------|------|
| `MarkdownStructuredSplitter` / Parser / Embedding | 与多库无关 |
| KB 权重设置 | 需求明确"各库地位相同" |
| 文档上传、列表页、知识库管理 | 不在本次范围 |
| 单库 retrieve 路径 | 向后兼容，旧 curl 零破坏 |
| QPS 限流逻辑 | 已按 tenant 计，不按库数倍增 |
| 日检索配额计数 | 已只计 1 次（router:253） |

---

## 六、风险评估

| 风险 | 级别 | 缓解 |
|------|------|------|
| per-KB 重构破坏单库路径 | 中 | 单库时 `asyncio.gather` 只有一个 task，行为等价于原来；需要充分的单库回归测试 |
| ES BM25 跨库并行增加 ES 连接压力 | 低 | 已有连接池；2-3 个库的并发查询远低于池上限 |
| RRF 两阶段融合参数调优 | 低 | 复用现有 `HYBRID_RRF_K=60`；per-KB 和跨库 RRF 用同一个 k 是合理的 |
| 前端 Checkbox 列表数据量大 | 低 | 一般 tenant 的 KB 数在几十以内，Tree API 已有分页 |

---

## 七、工作量估算

| 模块 | 预估改动量 | 复杂度 |
|------|-----------|--------|
| `RetrieveUseCase.execute` 重构 | ~100 行改写 | 高 — 核心逻辑 |
| `fusion.py` 新增跨库 RRF | ~40 行新增 | 中 |
| Plan presets + router 校验 | ~20 行 | 低 |
| SearchHit + 响应体扩展 | ~30 行 | 低 |
| 前端检索页改造 | ~150 行 | 中 |
| eval 适配 + golden cases | ~60 行 | 低 |
| 单元测试 + E2E 测试 | ~200 行 | 中 |
| **总计** | **~600 行** | |

---

## 八、与现有架构的契合度

**好消息**：代码库在多库方向上已经走了 60% 的路——`kb_ids` 从 API 到日志全程贯穿，租户校验、存在性校验、5 库硬上限都已就位。

**唯一的结构性缺口**：检索执行体仍然是"跨库单次查询"而非"per-KB 并行召回 + 跨库 RRF"。这 100 行的 `RetrieveUseCase.execute` 重构是本次融合的核心。
