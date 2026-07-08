# query-processing-pipeline

Pipeline 串联改写和词表扩展，填充完整的 `QueryProcessResult`。

## ADDED Requirements

### Requirement: QueryProcessResult 数据结构

The system SHALL implement this requirement.

```python
@dataclass
class QueryProcessResult:
    raw_query: str               # 用户原话，全程不变
    effective_query: str         # LLM 改写后；未改写时 = raw_query
    search_query: str            # 追加扩展词后；无扩展时 = effective_query
    needs_rewrite: bool          # LLM 判断是否需要改写
    strategy: str                # "rewrite" | "noop"
    rewrite_latency_ms: int      # 改写耗时；未改写时 = 0（哨兵值，非实际测量）
    degraded: bool               # 改写是否失败降级
    degraded_reason: str | None  # 降级原因
    synonym_applied: bool        # 词表是否命中
    synonym_expansions: list[str] # 本次追加的扩展词列表
```

各字段的填充职责：

| 字段组 | 填充者 |
|--------|--------|
| raw_query, effective_query, needs_rewrite, strategy, rewrite_latency_ms, degraded, degraded_reason | RewritePort.rewrite() |
| search_query, synonym_applied, synonym_expansions | QueryPipeline（调用 SynonymExpander 后覆盖） |

改写器返回时 synonym 字段保持默认值（`synonym_applied=False`, `synonym_expansions=[]`, `search_query=effective_query`）。

#### Scenario: 改写和词表同时开
- **GIVEN** `enabled=true`, KB 有 synonyms
- **WHEN** `process(raw_query="背调要问啥", kb_context=..., synonyms=[...], enabled=true)`
- **THEN** `raw_query` = "背调要问啥"
- **AND** `effective_query` 为改写后的句子
- **AND** `search_query` 含扩展词
- **AND** `needs_rewrite` = true
- **AND** `degraded` = false
- **AND** `synonym_applied` = true

#### Scenario: 仅改写，无词表
- **GIVEN** `enabled=true`, `synonyms=[]`
- **WHEN** process
- **THEN** `synonym_applied` = false, `search_query` = `effective_query`

#### Scenario: enabled=false，全无处理
- **GIVEN** `enabled=false`
- **WHEN** process
- **THEN** `QueryProcessResult` 所有 query 字段相同
- **AND** `needs_rewrite` = false, `degraded` = false, `strategy` = "noop"
- **AND** `synonym_applied` = false

### Requirement: 降级不阻断检索

The system SHALL implement this requirement.

LLM 改写失败时，`effective_query` 回退为 `raw_query`，标记 `degraded=true`，检索照常继续。

#### Scenario: rewrite() 抛异常
- **GIVEN** LLM API key 错误
- **WHEN** pipeline 调用 rewrite()
- **THEN** pipeline 捕获异常，构造 `QueryProcessResult`:
- **AND** `degraded` = true, `effective_query` = `raw_query`, `needs_rewrite` = false
- **AND** 检索正常执行，code = 0

#### Scenario: rewrite() 返回但 LLM 内部降级
- **GIVEN** LLM 调用成功但返回 JSON 解析失败
- **WHEN** rewrite() 内部降级
- **THEN** 返回的 `QueryProcessResult.degraded` = true（改写器设置）
- **AND** pipeline 直接透传，词表基于 `effective_query`（= raw_query）扩展

### Requirement: 改写耗时独立

The system SHALL implement this requirement.

`rewrite_latency_ms` 仅计 `rewrite()` 调用耗时。词表扩展耗时、检索耗时不计入。

#### Scenario: 改写耗时不计入检索延迟
- **GIVEN** 改写耗时 480ms, 检索耗时 150ms
- **WHEN** retrieve 完成
- **THEN** `query_processing.rewrite_latency_ms` ≈ 480
- **AND** `meta.latency_ms` ≈ 150
