# Comet Design Handoff

- Change: retrieval-robustness
- Phase: design
- Mode: compact
- Context hash: 4809e63cbe972fc010ec35e202ea00004973224cd822695d9560b78ce81e8cf9

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/retrieval-robustness/proposal.md

- Source: openspec/changes/retrieval-robustness/proposal.md
- Lines: 1-22
- SHA256: eb8f20db305c9d3bb76fe71e1e51ad1fdb2b02d9af2b9a198be7ef5d6eba2f6c

```md
## Why

RAGNexus 检索链路的容错机制存在不对称和不完整的问题：BM25 挂了能降级为纯向量，但向量服务挂了不能反向降级为纯 BM25；多库检索中一个库失败就拖垮整个请求；空结果和系统错误在调用方看来完全一样。这导致「依赖抖一下，整个请求就失败」，用户得不到任何有用信息。

索引链路的容错已经完善（Celery 重试 + 事务回滚），检索链路需要补齐对应的容错能力，实现「能降级的尽量降，实在不行才拒绝，并在 metadata 里诚实地标记打了什么折」。

## What Changes

- **Hybrid 双向降级标记完善**：`_retrieve_per_kb` 已实现双向 try/except 降级（vector 失败→BM25，BM25 失败→vector），补充降级时的 metadata 标记（`degraded=true` + `degraded_reason`）
- **多库 partial 容错标记透传**：`execute` 已通过 `asyncio.gather(return_exceptions=True)` 实现单库失败跳过，补充 `failed_kb_ids`、`partial_kb_success` 字段并透传到 API 响应
- **空结果语义区分**：新增 `empty_reason` 字段，区分 `no_indexed_chunks`（无索引 chunk）和 `no_chunks_matched`（有 chunk 但无命中）
- **query 边界校验配置化**：将硬编码的 `QUERY_MAX_LENGTH=2000` 改为环境变量
- **单测覆盖**：新增 `tests/test_retrieve_robustness.py`，覆盖 hybrid 降级、多库容错、query 边界等 7 个场景
- **集成验证脚本**：新增 `scripts/verify_robustness_retrieve.py`，停 ES 后验证降级行为

## Capabilities

### New Capabilities
- `retrieval-robustness`: 检索链路的降级容错与空结果语义区分，包含 metadata 诚实标记

### Modified Capabilities
无——本次改动不改变已有 capability 的 spec 级行为，仅补齐容错路径的 metadata 标记和透传。核心检索逻辑（RRF 融合、rerank、rewrite）保持不变。
```

## openspec/changes/retrieval-robustness/design.md

- Source: openspec/changes/retrieval-robustness/design.md
- Lines: 1-109
- SHA256: e1e28cddd6361d339627bb9de0369edf4d0545761e53d94037b932821e855cc9

[TRUNCATED]

```md
## Context

RAGNexus 检索链路当前架构：

```
词表扩展 → Query 改写 → Embedding → vector/bm25/hybrid
  → 多库并行 (asyncio.gather) → 跨库 RRF → rerank → chunks
```

**已有容错能力**：
- Query 改写失败 → 降级用原 query
- BM25 异常 → 降级纯 vector（`_retrieve_per_kb` L437-452）
- Vector 异常 → 降级纯 BM25（`_retrieve_per_kb` L420-435）
- Rerank 失败 → 降级返回原始结果
- 多库单库异常 → 跳过该库（`return_exceptions=True`，L224）
- Langfuse 不可用 → 跳过 trace

**缺失的是「诚实标记」**：上述降级发生后，API 响应 metadata 中缺少对应的标记字段，调用方无法区分「正常结果」「降级结果」「空结果」。

**约束**：
- 不新增 API 路由
- 不修改数据库 schema
- 不修改前端
- 不新增外部依赖
- Happy path 行为完全不变

## Goals / Non-Goals

**Goals:**
- Hybrid 降级时在 metadata 中标记 `degraded=true` 及具体原因
- 多库 partial 失败时在 API 响应中透传 `failed_kb_ids` 和 `partial_kb_success`
- 空结果时区分原因（`empty_reason`）
- query 边界校验改用 `QUERY_MAX_LENGTH` 环境变量
- 新增单测覆盖降级路径
- 新增集成验证脚本

**Non-Goals:**
- 不改造索引链路
- 不改变 RRF 融合算法
- 不改变 rerank/rewrite 逻辑
- 不新增观测模块（复用 Langfuse + retrieval_log）
- 不在第一阶段实现 `empty_reason` 的两级精确区分（`no_indexed_chunks` vs `no_chunks_matched` 先合并为单一标记，后续迭代细化）

## Decisions

### 1. `_retrieve_per_kb` 返回值扩展

**决策**：将返回值从 `tuple[list[SearchHit], int, int]` 扩展为包含降级标记的结构。

**备选**：在 `execute` 层面额外追踪降级状态。但这样会丢失 per-KB 粒度的降级原因。

**选择理由**：per-KB 降级原因需要在该方法内部确定（知道哪路失败了），在 `execute` 层做需要重复判断逻辑。扩展返回值是成本最低的方案。

**实现**：定义轻量 dataclass 或 named tuple：
```python
@dataclass
class PerKbRetrieveResult:
    hits: list[SearchHit]
    vec_count: int
    kw_count: int
    degraded: bool = False
    degraded_reason: str | None = None
```

### 2. metadata 字段设计

**决策**：在 `RetrieveResult` 新增三个字段并在 router 响应中透传。

| 字段 | 类型 | 触发条件 |
|------|------|---------|
| `failed_kb_ids` | `list[str]` | 多库检索中有 KB 召回异常 |
| `partial_kb_success` | `bool` | 至少一个 KB 成功 + 至少一个失败 |
| `empty_reason` | `str \| None` | 检索成功但 chunks=[] |

**备选**：复用 `degraded_kb_ids` 统一记录失败和空 KB。但语义混淆（失败 vs 空结果原因不同），不利于业务方处理。

**选择理由**：明确语义边界——`degraded_kb_ids` 记录「降级/空」的 KB，`failed_kb_ids` 记录「异常失败」的 KB，调用方可据此做不同处理。

### 3. `empty_reason` 分级策略

```

Full source: openspec/changes/retrieval-robustness/design.md

## openspec/changes/retrieval-robustness/tasks.md

- Source: openspec/changes/retrieval-robustness/tasks.md
- Lines: 1-26
- SHA256: cd085ff93e4c298f8a3cf2c934328315c40642132a8652e868716806e50e2dc6

```md
## 1. 数据模型扩展

- [ ] 1.1 `RetrieveResult` 新增字段：`failed_kb_ids`、`partial_kb_success`、`empty_reason`
- [ ] 1.2 定义 `PerKbRetrieveResult` dataclass 替换 `_retrieve_per_kb` 的三元组返回值

## 2. 核心逻辑改造

- [ ] 2.1 `_retrieve_per_kb` 返回值改为 `PerKbRetrieveResult`，包含降级标记 `degraded` 和 `degraded_reason`
- [ ] 2.2 `execute` 中 per-KB 降级标记聚合：汇总 `degraded`、设置 `partial_kb_success`
- [ ] 2.3 `execute` 中区分 `failed_kb_ids`（异常）和 `degraded_kb_ids`（降级/空）语义
- [ ] 2.4 `execute` 中计算 `empty_reason`：chunks=[] 时标记原因
- [ ] 2.5 `execute` 中 query 长度校验改用 `QUERY_MAX_LENGTH` 环境变量

## 3. API 响应透传

- [ ] 3.1 `retrieve_router.py` 响应 meta 中透传 `degraded_kb_ids`、`failed_kb_ids`、`partial_kb_success`、`empty_reason`
- [ ] 3.2 确保 Happy path（单库 balanced）响应结构向后兼容，不出现退化标记

## 4. 测试

- [ ] 4.1 新建 `tests/test_retrieve_robustness.py`，mock 方式覆盖 7 个场景
- [ ] 4.2 新建 `scripts/verify_robustness_retrieve.py` 集成验证脚本

## 5. 配置

- [ ] 5.1 `.env.example` 补充 `QUERY_MAX_LENGTH=2000` 配置项说明
```

## openspec/changes/retrieval-robustness/specs/retrieval-robustness/spec.md

- Source: openspec/changes/retrieval-robustness/specs/retrieval-robustness/spec.md
- Lines: 1-57
- SHA256: 629fe0e48072eb9d9aad16421e2dbfad65a14a6a2b6f98489505be421373bd10

```md
## ADDED Requirements

### Requirement: Hybrid 检索双向降级时 SHALL 在 metadata 中标记降级状态

检索在 hybrid 模式下执行时，若向量检索或 BM25 检索中任一路失败，系统 SHALL 自动降级为另一路可用检索方式继续执行，并 SHALL 在返回结果的 metadata 中标记 `degraded=true` 及对应的 `degraded_reason`。

#### Scenario: 向量检索失败时降级为纯 BM25
- **WHEN** hybrid 模式下向量检索抛出异常
- **THEN** 系统自动降级为纯 BM25 检索并返回结果，`metadata.retrieval.degraded=true`，`degraded_reason` 包含向量失败信息

#### Scenario: BM25 检索失败时降级为纯向量
- **WHEN** hybrid 模式下 BM25 检索抛出异常
- **THEN** 系统自动降级为纯向量检索并返回结果，`metadata.retrieval.degraded=true`，`degraded_reason` 包含 BM25 失败信息

#### Scenario: 两路检索都失败时拒绝请求
- **WHEN** hybrid 模式下向量检索和 BM25 检索均失败
- **THEN** 系统 SHALL 返回 RETRIEVAL_FAILED 错误码，不返回 200

#### Scenario: 单模式检索失败时拒绝请求
- **WHEN** 检索模式为 vector 或 bm25（非 hybrid）且对应检索失败
- **THEN** 系统 SHALL 返回对应错误码，不降级到其他模式

### Requirement: 多知识库检索 SHALL 支持 partial 容错

当一次检索请求包含多个知识库时，若部分知识库检索失败，系统 SHALL 继续返回成功库的检索结果，并 SHALL 在 metadata 中标记 `partial_kb_success=true` 和 `failed_kb_ids`。

#### Scenario: 多库中单库失败时返回其余库结果
- **WHEN** 检索请求包含 3 个知识库，其中 1 个检索异常
- **THEN** 系统返回 code=0，chunk 来自成功库，`metadata.retrieval.partial_kb_success=true`，`failed_kb_ids` 包含失败库 ID

#### Scenario: 多库全部失败时拒绝请求
- **WHEN** 检索请求包含的所有知识库均检索失败
- **THEN** 系统 SHALL 返回 RETRIEVAL_FAILED 错误码

### Requirement: 空检索结果 SHALL 区分原因

当检索成功但未返回任何 chunk 时，系统 SHALL 在 metadata 中标记 `empty_reason` 以区分空结果与系统错误。

#### Scenario: 知识库无索引 chunk 时返回空结果标记
- **WHEN** 目标知识库下没有任何 SUCCESS 状态的文档 chunk
- **THEN** 系统返回 code=0，`retrieved_chunks=[]`，`metadata.retrieval.empty_reason` 非空

#### Scenario: 有 chunk 但检索无命中时返回空结果标记
- **WHEN** 目标知识库有索引 chunk 但检索未命中任何结果
- **THEN** 系统返回 code=0，`retrieved_chunks=[]`，`metadata.retrieval.empty_reason` 非空

### Requirement: query 参数边界 SHALL 通过环境变量配置

系统 SHALL 通过 `QUERY_MAX_LENGTH` 环境变量（默认 2000）配置 query 最大长度限制。空 query 或超长 query SHALL 返回 PARAM_ERROR。

#### Scenario: 空 query 被拒绝
- **WHEN** 检索请求的 query 参数为空字符串或全空格
- **THEN** 系统返回 PARAM_ERROR 错误码

#### Scenario: 超长 query 被拒绝
- **WHEN** 检索请求的 query 参数长度超过 QUERY_MAX_LENGTH
- **THEN** 系统返回 PARAM_ERROR 错误码
```

