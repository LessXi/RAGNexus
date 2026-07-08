## ADDED Requirements

### Requirement: 多库并行召回

系统 SHALL 支持对 `kb_ids` 列表中的每个知识库执行独立的并行召回。每个库的召回流程为：向量检索 + BM25 关键词检索 → 库内 RRF 融合，各库并行（`asyncio.gather`），不互相阻塞。

每个库 SHALL 召回 `per_kb_top_k` 条候选，其中 `per_kb_top_k = max(top_k, vector_top_k, bm25_top_k, 10)`。向量搜索和 BM25 搜索 SHALL 均限定在当前库范围（`kb_id = <单库>`）。

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

跨库 RRF 融合 SHALL 使用与单库 hybrid RRF 相同的 `rrf_k` 参数（默认 60）。融合结果 SHALL 按 `rrf_score` 降序排列，取 `top_k` 条返回。融合新建的 `SearchHit` SHALL 保留原始 `kb_id`、`doc_id`、`chunk_id` 字段不变。

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

- **WHEN** 只传一个 kb_id
- **THEN** `meta.multi_kb` SHALL 为 false（或字段不存在）
- **AND** 单库路径行为与改前完全一致

### Requirement: 多库检索配额计数

一次多库 retrieve SHALL 仅消耗 1 次日检索配额，不按库数倍增。QPS 限流 SHALL 同理按 tenant 计，不按库数倍增。

#### Scenario: 双库检索配额只计 1 次

- **GIVEN** 租户日检索配额初始为 N
- **WHEN** 执行一次双库 retrieve 成功
- **THEN** 日检索计数 SHALL 增加 1（而非 2）

### Requirement: 多库检索向后兼容

单 `kb_id` 调用方式 SHALL 完全向后兼容。传入 `kb_ids: ["single_kb"]` SHALL 与改前传入 `kb_id` 行为一致。已存在的 curl 调用和集成代码 SHALL 不需要任何修改。

#### Scenario: 旧单库 curl 行为不变

- **GIVEN** 改前可用的单库检索 curl 命令
- **WHEN** 升级后执行同一 curl 命令
- **THEN** 响应结构 SHALL 兼容（新增字段为加法，不破坏已有字段）
- **AND** 检索结果 SHALL 与改前一致

### Requirement: per-KB 降级处理

系统 SHALL 支持 per-KB 级别的降级处理。当某个 KB 的 BM25 搜索失败（如 ES 不可达）时，该 KB SHALL 降级为纯向量召回，不影响其他 KB 的正常并行召回。若某 KB 的向量搜索也失败，该 KB SHALL 被整体跳过（返回空列表）。最终跨库 RRF SHALL 仅融合成功返回的 KB 候选。

降级信息 SHALL 记录在日志中，包含 `degraded_kb_id` 和 `degraded_reason`。

#### Scenario: 单库 BM25 失败时降级

- **GIVEN** 双库检索中 KB_A 的 ES 不可用
- **WHEN** 执行 per-KB 并行召回
- **THEN** KB_A SHALL 降级为纯向量召回
- **AND** KB_B SHALL 正常执行 vector+BM25 → 库内 RRF
- **AND** 跨库 RRF SHALL 融合两库的候选
- **AND** 日志 SHALL 包含 `degraded_kb_id: "KB_A"` 和降级原因

#### Scenario: 单库完全失败时跳过

- **GIVEN** 双库检索中 KB_A 的 pgvector 和 ES 均不可用
- **WHEN** 执行 per-KB 并行召回
- **THEN** KB_A SHALL 返回空列表
- **AND** KB_B SHALL 正常执行
- **AND** 跨库 RRF SHALL 只用 KB_B 的候选（单组退化）
