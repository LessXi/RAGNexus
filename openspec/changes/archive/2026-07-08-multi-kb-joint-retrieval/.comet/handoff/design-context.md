# Comet Design Handoff

- Change: multi-kb-joint-retrieval
- Phase: design
- Mode: compact
- Context hash: 376070b040ab7a567728e9e088b0fe50cf474be61a4d2ea7d49b261c9b8a4dd6

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/multi-kb-joint-retrieval/proposal.md

- Source: openspec/changes/multi-kb-joint-retrieval/proposal.md
- Lines: 1-29
- SHA256: 9e5564402bd96e202b2e6102bf75db26f67615f8c7a311d9cebfc352bc5009bb

```md
## Why

当前 `/v1/rag:retrieve` 的 API 虽然已接受 `kb_ids` 列表，但检索执行体仍是"跨库一次查询 + BM25 只查第一个库"的半成品。当用户问题横跨多个知识库时，BM25 结果缺失、跨库 score 不可比，导致融合结果偏向单个库。业务方要么自行调两次接口再手动合并，要么把所有文档混入一个大库，把本应由中台解决的问题推回给接入方。

## What Changes

- **检索管道重构**：`RetrieveUseCase.execute` 改为 per-KB 并行召回（每个库独立 vector + BM25 → 库内 RRF），再跨库 RRF 融合，替代当前的"向量跨库 + BM25 单库"模式
- **跨库 RRF 融合**：在 `domain/retrieval/fusion.py` 新增 `cross_kb_rrf_fuse`，基于 per-KB rank 进行第二层 RRF 融合
- **Plan 配额联动**：Plan 预设新增 `max_kb_per_retrieve` 字段（free=1 / standard=3 / pro=5），替代硬编码的 5 库上限
- **响应体扩展**：chunk 新增 `kb_name` 字段，响应 `data` 返回 `kb_ids`，`meta` 增加多库融合信息（`multi_kb`, `fusion`, `kb_count` 等）
- **前端检索页改造**：单 KB 输入框 → Checkbox 多选（从 Tree API 拉取列表），chunk 卡片增加来源库 Badge
- **eval 适配**：dataset case 支持 `kb_ids` 字段，新增跨库 golden cases，Langfuse 导出脚本适配

## Capabilities

### New Capabilities
- `multi-kb-retrieval`: 多知识库联合检索 — per-KB 并行召回、跨库 RRF 融合、响应 chunk 携带来源库信息

### Modified Capabilities
- `retrieve-api`: API 契约扩展 — 响应 `data` 显式返回 `kb_ids`，`meta` 增加 `multi_kb`/`fusion`/`kb_count` 多库元信息
- `tenant-plans`: Plan 预设新增 `max_kb_per_retrieve` 字段，按套餐分级管控多库检索上限

## Impact

- **后端核心**：`src/ragnexus/application/retrieve_use_case.py`（~100 行重构）、`src/ragnexus/domain/retrieval/fusion.py`（新增跨库 RRF）、`src/ragnexus/tenant/plan_presets.py`（新增字段）
- **HTTP 层**：`src/ragnexus/adapters/http/retrieve_router.py`（响应体扩展 + plan 校验）
- **前端**：`admin/src/pages/` 检索页（~150 行）、`admin/src/types/api.ts`（类型定义）
- **eval**：`scripts/run_retrieval_eval.py`、`scripts/export_eval_cases_from_langfuse.py`、新增 `eval/datasets/multi_kb_cases.json`
- **不涉及**：chunking、embedding、parser、文档上传、知识库管理、列表页
```

## openspec/changes/multi-kb-joint-retrieval/design.md

- Source: openspec/changes/multi-kb-joint-retrieval/design.md
- Lines: 1-86
- SHA256: ca9173f903c12165bf45088e0cb40bc8b965d9dba7b9923c47fd96c5df1f95dd

[TRUNCATED]

```md
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

**选择**：`per_kb_top_k = max(top_k, vector_top_k, 10)`。

**为何**：每库先多捞一点保证融合候选池充足（2 个库 × 10 = 20 候选，取 top 5），但又不过度放大 ES 和 pgvector 压力。

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
```

Full source: openspec/changes/multi-kb-joint-retrieval/design.md

## openspec/changes/multi-kb-joint-retrieval/tasks.md

- Source: openspec/changes/multi-kb-joint-retrieval/tasks.md
- Lines: 1-51
- SHA256: 9d033b2912a088467e70fe3f3399073766ea0280fc13592bea14ae8746bf0359

```md
## 1. 后端核心 — 检索管道重构

- [ ] 1.1 新增 `cross_kb_rrf_fuse` 函数到 `src/ragnexus/domain/retrieval/fusion.py`：接受多组 rank-ordered hits（每组是一个 KB 的候选），按 `1/(k+rank)` 跨库 RRF 融合
- [ ] 1.2 重构 `RetrieveUseCase.execute` 检索体：将"向量跨库 + BM25 单库"改为 per-KB `asyncio.gather` 并行召回，每个 KB 内独立 vector+BM25 → 库内 RRF，再跨库 RRF 融合
- [ ] 1.3 `_retrieve_candidates` 辅助方法：封装单库召回逻辑（向量 + BM25 → RRF），返回 rank-ordered hits
- [ ] 1.4 `SearchHit` dataclass 新增 `kb_name: str` 字段
- [ ] 1.5 预加载 `kb_id → kb_name` 映射（批量 SELECT），跨库 RRF 后逐 chunk 填充 `kb_name`
- [ ] 1.6 `per_kb_top_k` 配置化：`max(top_k, vector_top_k, 10)`，确保融合候选池充足

## 2. Plan 配额联动

- [ ] 2.1 `plan_presets.py` 三档套餐 `limits` 新增 `max_kb_per_retrieve` 字段（free=1, standard=3, pro=5）
- [ ] 2.2 `retrieve_router.py` 入口校验：`len(req.kb_ids) <= plan_ctx.limits.max_kb_per_retrieve`，超限返回 `FEATURE_NOT_ALLOWED (20013)`
- [ ] 2.3 保留 `MULTI_KB_MAX=5` 硬上限作为天花板

## 3. 响应体扩展

- [ ] 3.1 `retrieve_router.py` 响应 `data` 根级新增 `kb_ids` 字段
- [ ] 3.2 响应 `meta` 新增多库融合元信息：`multi_kb`, `kb_count`, `per_kb_top_k`, `fusion`, `rrf_k`
- [ ] 3.3 `_serialize_hit` 输出 `kb_name` 字段

## 4. 前端 — 检索页改造

- [ ] 4.1 检索范围区从单 KB 输入框改为 Checkbox 多选列表（数据源：`GET /v1/knowledge-bases/tree`）
- [ ] 4.2 至少勾选一个库才允许提交，否则提示「请选择至少一个知识库」
- [ ] 4.3 列表页「去检索」跳转时对应库默认勾选
- [ ] 4.4 chunk 卡片增加来源库 Badge（取 `kb_name`，不同颜色区分）
- [ ] 4.5 运行摘要区展示联查库数和融合方式
- [ ] 4.6 `20013` 错误时展示 plan 限制提示

## 5. Eval & 脚本适配

- [ ] 5.1 `scripts/run_retrieval_eval.py` 适配：读 case 时优先 `kb_ids`，回退 `kb_id`
- [ ] 5.2 新增 `eval/datasets/multi_kb_cases.json`：2-3 条跨库 golden case
- [ ] 5.3 `scripts/export_eval_cases_from_langfuse.py` 适配：优先取 `kb_ids` 字段
- [ ] 5.4 `RetrieveRequest` TypeScript 类型更新（如需要新增字段）
- [ ] 5.5 `docs/tenant-onboarding.md` 更新：增加 `max_kb_per_retrieve` 说明

## 6. 测试与验收

- [ ] 6.1 单元测试：`test_retrieve_use_case` 覆盖单库路径、双库 RRF、多库 plan 拦截
- [ ] 6.2 单元测试：`test_fusion` 覆盖 `cross_kb_rrf_fuse` 多组输入、rank 均衡、单组退化
- [ ] 6.3 单元测试：`test_plan_presets` 验证 `max_kb_per_retrieve` 各 plan 值
- [ ] 6.4 E2E 测试：单库向后兼容（旧 curl 行为不变）
- [ ] 6.5 E2E 测试：双库 RRF 融合验证（chunk 带 kb_id/kb_name，meta 多库信息）
- [ ] 6.6 E2E 测试：跨 tenant 隔离（混入其他租户库 → NOT_FOUND）
- [ ] 6.7 E2E 测试：free plan 拦截（传 2 库 → 20013）
- [ ] 6.8 E2E 测试：配额计数验证（双库检索仅计 1 次）
- [ ] 6.9 E2E 测试：不存在的库 ID → 整体失败
- [ ] 6.10 eval regression：原 `ecommerce_retrieval.json` 单库分数与 baseline 一致
- [ ] 6.11 eval 跨库验证：`multi_kb_cases.json` 的 `context_recall` 明显高于单库
```

## openspec/changes/multi-kb-joint-retrieval/specs/multi-kb-retrieval/spec.md

- Source: openspec/changes/multi-kb-joint-retrieval/specs/multi-kb-retrieval/spec.md
- Lines: 1-104
- SHA256: a097b16b1d95cabd02f4cc40fb30e9a45713f767a497a46184380fc2c09a3e79

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: 多库并行召回

系统 SHALL 支持对 `kb_ids` 列表中的每个知识库执行独立的并行召回。每个库的召回流程为：向量检索 + BM25 关键词检索 → 库内 RRF 融合，各库并行（`asyncio.gather`），不互相阻塞。

每个库 SHALL 召回 `per_kb_top_k` 条候选，其中 `per_kb_top_k = max(top_k, vector_top_k, 10)`。向量搜索和 BM25 搜索 SHALL 均限定在当前库范围（`kb_id = <单库>`）。

query 处理（词表扩展 / LLM 改写）SHALL 只执行一次，不随库数倍增。embedding 计算 SHALL 只执行一次，所有库复用同一个 search_vector。

#### Scenario: 双库并行召回

- **GIVEN** 租户有两个知识库 kb_ecommerce 和 kb_customer_service
- **WHEN** 调用 `POST /v1/rag:retrieve` 传 `kb_ids: ["kb_ecommerce", "kb_customer_service"]`
- **THEN** 两个库的 vector + BM25 召回 SHALL 并行执行
- **AND** 每个库召回不超过 per_kb_top_k 条候选
- **AND** 向量搜索 embedding 仅计算一次

#### Scenario: 单库退化为原有行为

- **GIVEN** `kb_ids` 仅含一个库
- **WHEN** 执行检索
- **THEN** 库内 RRF 后跨库 RRF SHALL 退化为恒等映射
- **AND** 行为 SHALL 与改前单库检索一致

### Requirement: 跨库 RRF 融合

系统 SHALL 对 per-KB 并行召回的候选执行跨库 RRF 融合。每条候选的 RRF 分数 SHALL 基于其库内 rank 计算：`rrf_score = 1 / (rrf_k + rank_in_kb)`，其中 rank 从 1 开始。若同一 chunk_id 命中多个库（未来可能），SHALL 累加各库的 RRF 贡献分。

跨库 RRF 融合 SHALL 使用与单库 hybrid RRF 相同的 `rrf_k` 参数（默认 60）。融合结果 SHALL 按 `rrf_score` 降序排列，取 `top_k` 条返回。

#### Scenario: RRF 均衡覆盖多库

- **GIVEN** 两个库各召回 10 条候选
- **WHEN** 跨库 RRF 融合后取 top_k=5
- **THEN** 结果 SHALL 不会让某个库的 chunk 全部占满前 5
- **AND** 若两个库都有相关内容，各自均有 chunk 进入 top_k

#### Scenario: 单库时 RRF 不额外改变排序

- **WHEN** `kb_ids` 仅含一个库
- **THEN** 跨库 RRF 融合 SHALL 不改变库内 RRF 的排序

### Requirement: chunk 携带来源库信息

每条 `SearchHit` SHALL 携带 `kb_id` 和 `kb_name` 字段。`kb_name` SHALL 在检索开始时通过批量查询 `knowledge_bases` 表预加载（`kb_id → kb_name` 映射），跨库 RRF 融合后逐 chunk 填充。

#### Scenario: 检索响应中每条 chunk 带 kb_id 和 kb_name

- **WHEN** 多库检索返回结果
- **THEN** 每条 `hits[*]` SHALL 包含 `kb_id` 和 `kb_name`（或 `kb_id` 前 8 位作为回退）

### Requirement: 响应 data 显式返回 kb_ids

响应 `data` 根级别 SHALL 新增 `kb_ids` 字段，返回本次检索实际查询的知识库 ID 列表。

#### Scenario: 双库检索响应含 kb_ids

- **WHEN** 请求传入 `kb_ids: ["kb_ecommerce", "kb_customer_service"]`
- **THEN** 响应 `data.kb_ids` SHALL 为 `["kb_ecommerce", "kb_customer_service"]`

### Requirement: 响应 meta 新增多库融合元信息

响应 `meta` SHALL 新增以下字段描述多库检索信息：

- `multi_kb: bool` — 是否为多库检索（`len(kb_ids) > 1`）
- `kb_count: int` — 联查的库数量
- `per_kb_top_k: int` — 每个库的召回候选数
- `fusion: str` — 融合方式（`"rrf"`）
- `rrf_k: int` — RRF 参数 k

#### Scenario: 双库检索 meta 含多库信息

- **WHEN** 传两个 kb_ids 完成检索
- **THEN** `meta.multi_kb` SHALL 为 true
- **AND** `meta.kb_count` SHALL 为 2
- **AND** `meta.fusion` SHALL 为 "rrf"

#### Scenario: 单库检索 meta 不含多库信息或为 false

```

Full source: openspec/changes/multi-kb-joint-retrieval/specs/multi-kb-retrieval/spec.md

## openspec/changes/multi-kb-joint-retrieval/specs/retrieve-api/spec.md

- Source: openspec/changes/multi-kb-joint-retrieval/specs/retrieve-api/spec.md
- Lines: 1-146
- SHA256: b1f07c14f18b15bfb5b4b58cb8f8153cd06c16f760cc9d5d32ab192fc399730e

[TRUNCATED]

```md
## MODIFIED Requirements

### Requirement: POST /v1/rag:retrieve 请求新增 query_options

The system SHALL implement this requirement.

请求体新增可选字段 `query_options`：

```json
{
  "query_options": {
    "enabled": true,
    "strategy": "rewrite"
  }
}
```

- `enabled: bool` — 是否启用 query 处理（改写 + 词表扩展）
- `strategy: str` — 改写策略（当前仅 `"rewrite"`）。`enabled=false` 时忽略

#### Scenario: 传 query_options.enabled=true
- **WHEN** 请求包含 `query_options: { enabled: true, strategy: "rewrite" }`
- **THEN** 后端执行 LLM 改写 + 词表扩展（若 KB 配置了 synonyms）
- **AND** 响应 `meta.query_processing` 包含完整链路

#### Scenario: 不传 query_options
- **WHEN** 请求不包含 `query_options`
- **THEN** 行为与改前完全一致
- **AND** 响应 `meta.query_processing` 为 `null`

#### Scenario: enabled=false, strategy="rewrite"
- **WHEN** `query_options: { enabled: false, strategy: "rewrite" }`
- **THEN** `enabled` 优先，不执行任何处理
- **AND** `query_processing` 为 `null`

### Requirement: 响应新增 data.query

The system SHALL implement this requirement.

`data.query` 字段返回用户原始输入，始终不被改写后的句子替换。

#### Scenario: 开启改写时 data.query 不变
- **GIVEN** `query_options.enabled=true`
- **WHEN** 请求 `query="背调要问啥"`
- **THEN** 响应 `data.query` = "背调要问啥"
- **AND** `meta.query_processing.effective_query` 可能不同

#### Scenario: 不传 query_options 时 data.query 仍存在
- **WHEN** 请求不包含 `query_options`
- **THEN** `data.query` = 请求中的 query（新增字段，始终返回）

### Requirement: 响应 meta 新增 query_processing

The system SHALL implement this requirement.

响应 `meta` 新增可选字段 `query_processing`，类型为 `QueryProcessResult` 的 JSON 序列化，见原文各 Scenario。

### Requirement: 请求新增 profile 参数

检索请求体 SHALL 新增可选字段 `profile`，取值 speed / balanced / quality / custom。未传时默认 `balanced`。见原文各 Scenario。

### Requirement: 响应 meta 新增 tenant_policy

响应 `meta` SHALL 新增可选字段 `tenant_policy`，描述本次检索生效的策略参数。见原文各 Scenario。

### Requirement: 错误码 API_RATE_LIMIT 变更为 20005

`ErrorCode.API_RATE_LIMIT` 的业务错误码 SHALL 从 20002 改为 20005。HTTP 状态码 429 保持不变。

### Requirement: 新增错误码 FEATURE_NOT_ALLOWED (20013)

系统 SHALL 支持错误码 `FEATURE_NOT_ALLOWED` (20013, HTTP 403)，在 plan 不允许请求的 profile、options 或多库检索上限时返回。

#### Scenario: profile 超 plan 返回 20013
- **WHEN** free 租户传 profile=balanced
- **THEN** 系统 SHALL 返回 `"code": 20013, message: "当前套餐 free 不支持检索预设 balanced"`, HTTP 403

#### Scenario: 多库超 plan 上限返回 20013
- **WHEN** free 租户传 `kb_ids` 长度 > plan.max_kb_per_retrieve
- **THEN** 系统 SHALL 返回 `"code": 20013`，提示当前套餐最多支持 N 个库联合检索
```

Full source: openspec/changes/multi-kb-joint-retrieval/specs/retrieve-api/spec.md

## openspec/changes/multi-kb-joint-retrieval/specs/tenant-plans/spec.md

- Source: openspec/changes/multi-kb-joint-retrieval/specs/tenant-plans/spec.md
- Lines: 1-67
- SHA256: e1e9db223288abb138932cba2517ed1af0a16355ae42e77051f5956518e9e302

```md
## MODIFIED Requirements

### Requirement: 三档租户套餐定义

系统 SHALL 支持三档租户套餐（free、standard、pro），每档包含功能开关和配额上限，硬编码在 `plan_presets.py` 常量中。配额上限 SHALL 包含 `max_kb_per_retrieve` 字段，管控一次检索最多可联查的知识库数量。

#### Scenario: free 套餐限制
- **WHEN** 租户 plan 为 free
- **THEN** 该租户 SHALL 仅能使用 speed profile，最多 1 个知识库，单库 30 个文档，QPS 上限 3，日检索上限 500，不能使用 hybrid/rerank/rewrite
- **AND** `max_kb_per_retrieve` SHALL 为 1（仅支持单库检索）

#### Scenario: standard 套餐限制
- **WHEN** 租户 plan 为 standard
- **THEN** 该租户 SHALL 能使用 speed/balanced/custom profile，最多 5 个知识库，单库 200 个文档，QPS 上限 10，日检索上限 5000，可使用 hybrid 但不能用 rerank/rewrite
- **AND** `max_kb_per_retrieve` SHALL 为 3

#### Scenario: pro 套餐全功能
- **WHEN** 租户 plan 为 pro
- **THEN** 该租户 SHALL 能使用全部四档 profile，最多 50 个知识库，单库 5000 个文档，QPS 上限 50，日检索上限 100000，可使用全部功能
- **AND** `max_kb_per_retrieve` SHALL 为 5

### Requirement: 租户 plan 持久化与迁移

`tenants` 表 SHALL 新增 `plan VARCHAR(32) NOT NULL DEFAULT 'free'` 列。Alembic 迁移 SHALL 将已有租户设为 `standard`，`tenant_demo` 设为 `pro`。

#### Scenario: 新租户默认 free
- **WHEN** 通过 `create_tenant.py` 创建新租户且未指定 plan
- **THEN** 该租户的 plan SHALL 为 free

#### Scenario: 通过脚本修改 plan
- **WHEN** 执行 `update_tenant_plan.py --tenant-id <id> --plan <plan>`
- **THEN** 若 plan 为 free/standard/pro 之一，租户 plan SHALL 更新成功；若 plan 非法，脚本 SHALL 报错退出

### Requirement: 鉴权上下文携带 plan

`TenantContext` SHALL 包含 `plan` 字段。`get_by_hash()` SQL 查询 SHALL 从 JOIN 的 tenants 表顺路带回 plan 列。

#### Scenario: 鉴权成功携带 plan
- **WHEN** API Key 鉴权通过
- **THEN** `TenantContext.plan` SHALL 为对应租户的 plan 值

#### Scenario: 鉴权禁用时默认 plan
- **WHEN** `AUTH_ENABLED=false`
- **THEN** `_FALLBACK_TENANT.plan` SHALL 为 `pro`

## ADDED Requirements

### Requirement: 多库检索上限管控

系统 SHALL 在检索入口校验 `len(kb_ids) <= plan.limits.max_kb_per_retrieve`。超限时 SHALL 返回 `FEATURE_NOT_ALLOWED (20013)`，不执行检索。

系统 SHALL 保留硬上限 `MULTI_KB_MAX=5` 作为所有 plan 的天花板，`plan.max_kb_per_retrieve` 不得超过此值。

#### Scenario: free 租户多库被拦截

- **WHEN** free plan 租户传入 2 个 kb_ids
- **THEN** 系统 SHALL 返回 `code: 20013`，提示"当前套餐最多支持 1 个库联合检索"

#### Scenario: standard 租户 3 库通过

- **WHEN** standard plan 租户传入 3 个 kb_ids
- **THEN** 检索 SHALL 正常执行

#### Scenario: pro 租户 5 库通过

- **WHEN** pro plan 租户传入 5 个合法 kb_ids
- **THEN** 检索 SHALL 正常执行
```

