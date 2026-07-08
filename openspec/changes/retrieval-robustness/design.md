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

**决策**：一步到位实现两级区分（`no_indexed_chunks` / `no_chunks_matched`）。仅在 `chunks=[]` 时触发一次 `COUNT(*)` 查询，走索引，毫秒级开销。

**选择理由**：DB count 查询成本极低（仅在空结果路径触发），且飞书文档预定义了两种语义值。当前合并、后续再补 = 两次 change，边际成本高于一步做完。

### 4. `QUERY_MAX_LENGTH` 配置化

**决策**：从硬编码 `2000` 改为读取 `os.getenv("QUERY_MAX_LENGTH", "2000")`，在 `execute` 入口处校验。

**选择理由**：零破坏性改动，允许不同部署环境按需调整。

### 5. 单测策略

**决策**：新建 `tests/test_retrieve_robustness.py`，mock 方式覆盖 7 个场景：
1. mock vector 失败 → hybrid 降为 BM25，degraded=true
2. mock BM25 失败 → hybrid 降为 vector（回归）
3. mock 双路都失败 → RETRIEVAL_FAILED
4. mock 多库一库失败 → 另一库 chunk 仍在，failed_kb_ids 非空
5. mock 多库全部失败 → RETRIEVAL_FAILED
6. 空 query → PARAM_ERROR
7. 超长 query → PARAM_ERROR

## Risks / Trade-offs

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| `_retrieve_per_kb` 返回值签名变更影响调用方 | 低 | 仅 `execute` 内部调用 | 编译期即可发现 |
| `empty_reason` COUNT 查询增加延迟 | 低 | 仅在 chunks=[] 触发 | 走 kb_id 索引，毫秒级
| 验证脚本依赖 Docker ES | 中 | CI 无法运行 | ES 不可用时输出 SKIP + 原因 |
| 单测 mock 复杂度增加 | 低 | 需 mock 更多异常路径 | 复用现有 mock fixture 模式 |
