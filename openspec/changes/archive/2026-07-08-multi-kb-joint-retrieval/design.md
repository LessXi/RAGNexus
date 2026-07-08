## Context

当前 `RetrieveUseCase.execute` 已接受 `kb_ids: list[str]`，但检索执行体是"向量跨库单次查询 + BM25 仅查 `kb_ids[0]`"的半成品。向量搜索通过 pgvector `WHERE kb_id = ANY($1)` 跨库混排，BM25 只覆盖第一个库，融合时单次 RRF 混合向量和 BM25 结果——没有 per-KB 隔离，也没有跨库 RRF。

本设计基于飞书四篇需求文档（"为什么需要多知识库联合检索"、"多库并行召回与RRF融合提示词"、"调试台与测评适配提示词"、"测试验收"），在已有 `kb_ids` 基础设施上完成检索管道的结构性重构。

## Goals / Non-Goals

**Goals:**
- per-KB 并行召回（每个库独立 vector + BM25 → 库内 RRF），保证各库 BM25 和向量结果都能参与融合
- 跨库 RRF 融合，基于 per-KB rank 而非 raw score，解决跨库分数不可比问题
- Plan 分级管控多库上限（free=1 / standard=3 / pro=5），替代硬编码 5 库上限
- 响应 chunk 携带 `kb_id` 和 `kb_name`，响应 `meta` 增加多库融合元信息
- 前端检索页 Checkbox 多选 + chunk 来源库 Badge
- 单库路径向后兼容，旧 curl 零破坏

**Non-Goals:**
- 不改 chunking / embedding / parser / 文档上传 / 列表页
- 不做 KB 权重设置，各库地位相同
- 不新增外部依赖
- 不修改 `MarkdownStructuredSplitter`

## Decisions

### D1: 两阶段 RRF 融合（per-KB → cross-KB）

**选择**：每个库先独立做 vector+BM25 的库内 RRF，得到 rank-ordered top `per_kb_top_k` 候选；再对所有库的候选做跨库 RRF。

**替代方案**：保持当前"向量跨库 + BM25 多库并行 → 单次 RRF"模式。

**为何选择两阶段**：
- 向量 score 和 BM25 score 在不同库间不可直接比较（不同 chunking 策略导致 embedding 分布不同；BM25 的 IDF 是索引内归一化）
- RRF 只看 rank 不看 score，天然解决跨源比较问题
- 两阶段与单库 hybrid 的 RRF 是同一原理，不引入额外复杂度
- 单库 `len(kb_ids) == 1` 时等价于改前行为（库内 RRF + 跨库 RRF 退化为恒等映射）

### D2: `per_kb_top_k` 策略

**选择**：`per_kb_top_k = max(top_k, vector_top_k, bm25_top_k, 10)`。

**为何**：每库先多捞一点保证融合候选池充足（2 个库 × 10 = 20 候选，取 top 5）。同时包含 `bm25_top_k` 是因为 BM25 也需要足够的候选数来保证质量——仅用 `vector_top_k` 可能在纯 BM25 模式下候选不足。


### D7: 多库词表合并策略

**选择**：在 query 处理前批量加载所有 KB 的 settings，合并各库的 synonyms 列表（去重后合并），统一用于词表扩展。

**为何**：多库检索时，所有 KB 的内容都可能相关，应在词表扩展阶段就覆盖所有 KB 的术语。`kb_ids[0]` 的 synonyms 不足以覆盖跨库场景。

**实现**：遍历 `kb_ids` 批量 SELECT settings，合并 `synonyms` 列表去重后传给 `QueryPipeline.process`。

### D8: 多库改写上下文

**选择**：LLM 改写时 `kb_context` 改为包含所有 KB 的 name + description 列表（而非仅 `kb_ids[0]`），让 LLM 知道搜索范围横跨多个知识域。

**替代方案**：不改上下文，保持单库上下文。**不选择**，因为 LLM 不知道多库存在，可能把跨域问题改写为单域问题。

**实现**：将 `kb_context` 从单对象改为列表 `kb_contexts: list[dict]`，QueryPipeline 内部用列表生成改写 prompt。
### D3: `cross_kb_rrf_fuse` 函数位置

**选择**：新增在 `src/ragnexus/domain/retrieval/fusion.py`，与现有 `rrf_fuse` 同模块。

**为何**：两者共享 RRF 核心理念（rank-based 公式 `1/(k+rank)`），放在同一模块便于维护和复用 `_merge_metadata` 等工具函数。

### D4: Plan 字段命名

**选择**：在 `PLAN_PRESETS[plan]["limits"]` 下新增 `max_kb_per_retrieve`，与现有 `max_kb`（总知识库数上限）区分。

**为何**：`max_kb` 是"租户最多创建几个库"，`max_kb_per_retrieve` 是"一次检索最多查几个库"——语义不同，独立管控。

### D5: 配额计数策略

**选择**：一次多库 retrieve 日检索配额仍只计 1 次，不按库数倍增。

**当前已正确**：`rate_limiter.record_retrieve_success(tenant_id)` 在 router 的 finally 块内只调用一次。QPS 同理按 tenant 计。

### D6: kb_name 获取方式

**选择**：在 `RetrieveUseCase.execute` 开头预加载 `kb_id → kb_name` 映射（`SELECT id, name FROM knowledge_bases WHERE id = ANY($1)`），跨库 RRF 后逐 chunk 填充。

**替代方案**：在 `_serialize_hit` 中查库名。**不选择**，因为会使序列化层产生 I/O 依赖，破坏分层。

## Risks / Trade-offs

| Risk | Level | Mitigation |
|------|-------|------------|
| per-KB 重构破坏单库路径 | 中 | `len(kb_ids) == 1` 时 `asyncio.gather` 只有一个 task，库内 RRF 后跨库 RRF 退化为恒等映射；单库回归测试充分覆盖 |
| ES BM25 多连接并发增加压力 | 低 | 已有 asyncpg 连接池；2-3 个并发查询远低于池上限 |
| 两阶段 RRF 参数调优 | 低 | 复用现有 `HYBRID_RRF_K=60`，per-KB 和跨库 RRF 用同一个 k |
| 前端 Checkbox 列表数据量大 | 低 | 一般 tenant KB 数在几十以内，Tree API 已有分页 |
| 跨库检索延迟略增 | 低 | `asyncio.gather` 并行，延迟 ≈ max(单库)，非 sum；单库路径不变 |

## Migration Plan

1. **部署顺序**：后端先上（API 向后兼容，新增 `kb_ids` 多库支持），前端随后（Checkbox 多选适配）
2. **回滚策略**：单 `kb_id` 路径不变，回滚无风险；`kb_ids` 列表仅影响新调用方
3. **数据迁移**：`retrieval_logs.kb_ids` 已是 JSONB 字段，无需迁移
4. **Alembic**：无 schema 变更（`kb_ids` JSONB 已存在）

## Open Questions

- **租户隔离错误码**：已确认为 `NOT_FOUND`（`KNOWLEDGE_BASE_NOT_FOUND`），含 `missing_kb_id` 上下文。选择 404 而非 403 以不泄露其他 tenant 的 KB 存在性信息。
- 其余问题已在 D1-D8 决策中覆盖。
