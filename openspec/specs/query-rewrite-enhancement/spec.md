# query-rewrite-enhancement Specification

## Purpose
TBD - created by archiving change query-semantic-optimization. Update Purpose after archive.
## Requirements
### Requirement: RewritePort 接口签名

The system SHALL implement this requirement.

删除 `RewriteResult` dataclass。`RewritePort.rewrite()` 返回类型变更为 `QueryProcessResult`，新增 `kb_context` 参数：

```python
class RewritePort(Protocol):
    async def rewrite(
        self,
        *,
        query: str,
        kb_ids: list[str],
        kb_context: dict | None = None,
    ) -> QueryProcessResult: ...
```

`QueryProcessResult` 定义见 `query-processing-pipeline` spec。

#### Scenario: 接口变更后 LLMRewriteProvider 正常返回
- **GIVEN** `query="背调要问啥"`, `kb_context={name: "HR制度库", description: "..."}`
- **WHEN** 调用 `rewrite()`
- **THEN** 返回 `QueryProcessResult`，`raw_query` = "背调要问啥"
- **AND** `effective_query` 为改写后的句子
- **AND** `needs_rewrite` = true
- **AND** `degraded` = false
- **AND** `synonym_applied` = false, `synonym_expansions` = []（改写器不填）

#### Scenario: 无 kb_context 时兼容
- **GIVEN** `kb_context=None`
- **WHEN** 调用 `rewrite(query="背调要问啥", kb_ids=["KB_A"], kb_context=None)`
- **THEN** 改写正常执行，不报错

### Requirement: KB 上下文注入到 LLM prompt

The system SHALL implement this requirement.

`LLMRewriteProvider._call_llm()` 将 `kb_context` 中的 `name`、`description`、`rewrite_hint` 注入 system prompt。

#### Scenario: 有完整 kb_context 时 prompt 包含上下文
- **GIVEN** kb_context 包含 name="HR制度库", description="招聘、背调相关", rewrite_hint="面评=面试评价表"
- **WHEN** 调用 `_call_llm()`
- **THEN** LLM 收到的 prompt 包含 "知识库名称：HR制度库"、"知识库领域说明：招聘、背调相关"、"补充说明：面评=面试评价表"

#### Scenario: 仅 name 时 prompt 不崩
- **GIVEN** kb_context 仅含 name="HR制度库"，无 description 和 rewrite_hint
- **WHEN** 调用 `_call_llm()`
- **THEN** prompt 仅含 name，不含 description 和 rewrite_hint 相关文本

### Requirement: NoopRewriteProvider 适配新接口

The system SHALL implement this requirement.

`NoopRewriteProvider.rewrite()` 接受 `kb_context` 参数并忽略，返回 noop `QueryProcessResult`。

#### Scenario: Noop 返回 noop 结果
- **GIVEN** NoopRewriteProvider
- **WHEN** `rewrite(query="背调", kb_ids=["KB_A"], kb_context={...})`
- **THEN** 返回 `QueryProcessResult(raw_query="背调", effective_query="背调", search_query="背调", needs_rewrite=false, strategy="noop", degraded=false)`

