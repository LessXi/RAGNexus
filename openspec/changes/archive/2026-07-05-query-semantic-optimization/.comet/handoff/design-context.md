# Comet Design Handoff

- Change: query-semantic-optimization
- Phase: design
- Mode: compact
- Context hash: 92ce442263e468e6c2d966e56d5ef56f02aa95a0e5b41d9526b5c530ae834110

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/query-semantic-optimization/proposal.md

- Source: openspec/changes/query-semantic-optimization/proposal.md
- Lines: 1-36
- SHA256: 21810c77d2c0372d9fca35d74fd0121dce0cb997de6e228fc7f6794e6b43f00c

```md
## Why

当前 RAG 检索直接用用户原话做检索，口语化问法与文档专业术语词汇不重合（如"背调要问啥" vs "背景调查标准问题清单"），导致向量检索和关键词检索召回率不佳。虽然项目已有 LLM 改写基础设施（`RewritePort` + `LLMRewriteProvider`），但存在三个关键缺口：(1) 改写时 LLM 不知道知识库领域上下文，(2) 缺乏确定性的术语扩展机制，(3) 改写结果（`RewriteResult`）和未来扩展链路追踪的数据结构不统一，不便叠加新能力。

本次变更以"统一用 `QueryProcessResult` 替代 `RewriteResult`"为架构主轴，在不推翻现有 LLM 改写逻辑的前提下，叠加 KB 上下文注入、词表扩展和三阶段 pipeline，将检索链路升级为 `raw → effective → search_query`。

## What Changes

- **BREAKING**：删除 `RewriteResult` dataclass，统一用 `QueryProcessResult`。`RewritePort.rewrite()` 返回类型变更，所有调用方和测试必须适配
- **BREAKING**：`RewritePort.rewrite()` 接口签名新增 `kb_context: dict | None = None` 参数
- 新增 `SynonymExpander`：基于 KB 级词表的确定性术语扩展，纯规则匹配，不调 LLM
- 新增 `QueryPipeline`：串联改写 + 扩展，填充 `QueryProcessResult` 的 synonym 字段
- `knowledge_bases` 表新增 `settings` JSONB 字段，存储 synonyms 和可选 rewrite_hint
- `POST /v1/rag:retrieve` 请求新增可选 `query_options` 字段，响应新增 `data.query` 和 `meta.query_processing`
- 调试台新增「启用 query 改写」开关和运行摘要中的改写链路对比展示
- 新增 `scripts/update_kb_settings.py` 和 `scripts/generate_synonyms.py`
- LLM 改写 prompt 增加 `kb.name`、`kb.description`、可选 `rewrite_hint` 上下文

## Capabilities

### New Capabilities
- `query-rewrite-enhancement`：用 `QueryProcessResult` 统一改写输出，注入 KB 上下文增强改写精准度
- `synonym-expansion`：基于 KB 级可配置词表的确定性术语扩展
- `query-processing-pipeline`：Pipeline 串联改写和扩展，填充完整的 `QueryProcessResult`

### Modified Capabilities
- `retrieve-api`：请求增加 `query_options`，响应增加 `data.query` 和 `meta.query_processing`

## Impact

- **核心架构**：删除 `domain/ports.py` 中的 `RewriteResult`（4 字段），新增 `QueryProcessResult`（10 字段）。影响 8 个后端文件 + 5-7 个测试文件 + 1 个脚本
- **后端**：`adapters/rewrite/llm.py`（15 处字段映射）、`adapters/rewrite/noop.py`（3 处）、`application/retrieve_use_case.py`（5 处）、`composition.py`（2 处）、`adapters/http/retrieve_router.py`（4 处新增）
- **数据库**：`alembic/` 新增 `settings` JSONB migration
- **前端**：`admin/src/types/api.ts`、`admin/src/pages/retrieve.tsx`
- **新增文件**：`synonym_expander.py`、`pipeline.py`、`update_kb_settings.py`、`generate_synonyms.py`、`kb_settings.example.json`、alembic migration
- **测试**：`test_rewrite_port.py` 完全重写；`test_llm_rewrite.py`、`test_noop_rewrite.py`、`test_retrieve.py`、`test_retrieve_hybrid.py` 适配新接口；新增 `test_synonym_expander.py`、`test_pipeline.py`
```

## openspec/changes/query-semantic-optimization/design.md

- Source: openspec/changes/query-semantic-optimization/design.md
- Lines: 1-233
- SHA256: db807deb7d2a6209d370787dc97809b681fc29b5a9166ffd129177953723ba61

[TRUNCATED]

```md
## Context

RAGNexus 已有 LLM 改写基础设施（`RewritePort` 协议、`LLMRewriteProvider`、`NoopRewriteProvider`），在 `retrieve_use_case.py` 中接入检索链路。当前改写输出 `RewriteResult`（4 字段：`original_query`、`rewritten_query`、`needs_rewrite`、`reason`），LLM 自行判断是否需要改写，改写时不知晓知识库领域上下文。

本次变更的架构主轴：**删除 `RewriteResult`，统一用 `QueryProcessResult`（12 字段）替代。** 这样改写器直接输出完整结果，pipeline 只需补充 synonym 字段，不需要映射层。

## Goals / Non-Goals

**Goals:**
- 删除 `RewriteResult`，用 `QueryProcessResult` 统一所有 query 处理链路的数据结构
- `RewritePort.rewrite()` 注入 kb_context（name、description、rewrite_hint），返回 `QueryProcessResult`
- 新增 `SynonymExpander`：基于 `kb.settings.synonyms` 做精确子串匹配，命中则追加扩展词
- 新增 `QueryPipeline`：调用 rewrite → 调用 synonym_expander → 填充完整的 `QueryProcessResult`
- `knowledge_bases` 表增加 `settings` JSONB 字段
- API 请求新增 `query_options`，响应新增 `data.query` + `meta.query_processing`
- 调试台新增改写开关和链路展示
- 保留 `needs_rewrite` 语义（LLM 智能判断）
- 词表扩展受 `enabled` 控制

**Non-Goals:**
- 不改动 LLM 降级策略（缓存、5 层防御、精炼逻辑保持不变）
- 不改动 rerank 逻辑
- 不新增 LLM 模型配置（复用现有 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`）
- 不做词表在线编辑 UI
- 不做 A/B 对比模式（后续迭代）
- 不改动 `retrieve_logs` 表 schema（后续迭代）

## Decisions

### 1. 数据结构统一：删除 RewriteResult，All in QueryProcessResult

**决策**：

```python
# 旧（删除）
@dataclass
class RewriteResult:
    original_query: str
    rewritten_query: str
    needs_rewrite: bool
    reason: str

# 新
@dataclass
class QueryProcessResult:
    raw_query: str               # ← 原 original_query
    effective_query: str         # ← 原 rewritten_query
    search_query: str            # 新增：最终检索句（= effective + 扩展词）
    needs_rewrite: bool          # 保留
    strategy: str                # 新增："rewrite" | "noop"
    rewrite_latency_ms: int      # 新增
    degraded: bool               # 新增：改写是否降级
    degraded_reason: str | None  # 新增：降级原因
    synonym_applied: bool        # 新增
    synonym_expansions: list[str] # 新增
```

`RewritePort.rewrite()` 返回 `QueryProcessResult`。改写器只填 rewrite 相关字段，synonym 字段保持默认值。Pipeline 调用 synonym_expander 后补上 synonym 字段。

**理由**：减少一个 dataclass + 一个映射层。改写器和 pipeline 共享同一个数据结构，`search_query` 是检索时的唯一数据源——业务代码不用关心它来自改写还是扩展。

### 2. 改写模型：保留智能判断

**决策**：保留 `needs_rewrite` 语义，LLM 自行判断是否需要改写。`enabled=true` 时始终调用 LLM，但如果 LLM 判断不需要改写，`effective_query == raw_query`，`needs_rewrite=false`。

**理由**：精准 query（如"2024年Q3销售报告"）不需要改写。智能判断省 token、降延迟。与"总是改写"的区别可通过 `needs_rewrite` 字段观察。

### 3. 词表扩展开关：受 enabled 控制

**决策**：词表扩展与 LLM 改写共享 `query_options.enabled` 开关。不开改写时不做词表扩展。

**理由**：不开改写时拼接扩展词到原始口语 query 可能引入噪音。统一开关逻辑更干净。

### 4. RewritePort 接口变更

**决策**：
```python
class RewritePort(Protocol):
    async def rewrite(
        self,
```

Full source: openspec/changes/query-semantic-optimization/design.md

## openspec/changes/query-semantic-optimization/tasks.md

- Source: openspec/changes/query-semantic-optimization/tasks.md
- Lines: 1-90
- SHA256: aab9f0ae3e0d1c3557919e98396b67f580e42b0cb59a2c6efa373e6eadfd9c44

[TRUNCATED]

```md
## 1. 领域层：删除 RewriteResult，新增 QueryProcessResult

- [ ] 1.1 `domain/ports.py`：删除 `RewriteResult` dataclass（4 字段），新增 `QueryProcessResult` dataclass（12 字段：raw_query, effective_query, search_query, needs_rewrite, strategy, rewrite_latency_ms, degraded, degraded_reason, synonym_applied, synonym_expansions）
- [ ] 1.2 `domain/ports.py`：`RewritePort.rewrite()` 签名变更：新增 `kb_context: dict | None = None` 参数，返回类型 `RewriteResult` → `QueryProcessResult`
- [ ] 1.3 `domain/ports.py`：`KnowledgeBasePort` 增加 `get_settings(kb_id) -> dict` 和 `update_settings(kb_id, settings: dict)` 方法
- [ ] 1.4 `domain/models.py`：`KnowledgeBase` 模型增加 `settings: dict` 字段（默认 `{}`）

## 2. Alembic 数据库迁移

- [ ] 2.1 创建 migration：`knowledge_bases` 表增加 `settings JSONB NOT NULL DEFAULT '{}'`
- [ ] 2.2 `PgKnowledgeBaseRepository` 实现 `get_settings` / `update_settings`，create 时 settings 默认 `{}`
- [ ] 2.3 运行 `alembic upgrade head` 验证 migration 成功

## 3. 改写适配器：RewriteResult → QueryProcessResult

- [ ] 3.1 `llm.py`：所有 `RewriteResult(...)` 构造替换为 `QueryProcessResult(...)`（15 处：rewrite, _rewrite_impl, _layer5_checks, _check_cache, _write_cache, 5 个降级 return）
- [ ] 3.2 `llm.py`：`CacheEntry.rewrite_result` 类型 `RewriteResult` → `QueryProcessResult`
- [ ] 3.3 `llm.py`：`_call_llm()` 将 `kb_context`（name + description + rewrite_hint）注入 system prompt
- [ ] 3.4 `llm.py`：改写器内部计时，返回 `rewrite_latency_ms`；降级时设置 `degraded=True`，正常时 `degraded=False`
- [ ] 3.5 `noop.py`：`RewriteResult(...)` → `QueryProcessResult(...)`，接受 `kb_context` 参数并忽略

## 4. 词表扩展（新增）

- [ ] 4.1 新增 `adapters/rewrite/synonym_expander.py`：`SynonymExpander` 类
- [ ] 4.2 实现 `expand(effective_query, synonyms) -> (search_query, synonym_applied, expansions)`：中文精确子串匹配 + 英文 casefold + 去重 + 追加
- [ ] 4.3 容错：synonyms 格式异常时跳过该组，不抛异常
- [ ] 4.4 单元测试 `test_synonym_expander.py`：单组命中、多组命中+去重、未命中、英文大小写、空词表、格式错误容错、跨组扩展词去重

## 5. Pipeline 串联（新增）

- [ ] 5.2 实现 `process(raw_query, kb_context, synonyms, enabled) -> QueryProcessResult`：
  - `enabled=false` → 返回 noop `QueryProcessResult`（strategy="noop", 三阶段相同）
  - `enabled=true` → 调 `rewrite()` → 调 `SynonymExpander.expand()` → 覆盖 search_query 和 synonym 字段
  - `rewrite()` 抛异常 → 捕获，构造 `degraded=true` 的降级结果
  - 多 KB 时取 `kb_ids[0]` 对应的 KB 上下文（name、description、settings）
- [ ] 5.3 单元测试 `test_pipeline.py`：改写+扩展同开、仅改写、enabled=false、rewrite 异常降级、rewrite 内部降级透传

## 6. UseCase 和 Router 集成

- [ ] 6.1 `retrieve_use_case.py`：不再裸调 `rewriter.rewrite()`，改为调用 `pipeline.process()`；用 `search_query` 做 vector/bm25/hybrid 检索；传 `query_options` 透传
- [ ] 6.2 `retrieve_use_case.py`：KB 校验后取出 `name`、`description`、`settings`，组装 `kb_context` 和 `synonyms` 传给 pipeline
- [ ] 6.3 `composition.py`：实例化 `QueryPipeline`（注入 rewriter + synonym_expander），传给 use_case
- [ ] 6.4 `retrieve_router.py`：`_RetrieveRequest` 增加可选 `_QueryOptions`（enabled: bool, strategy: str）
- [ ] 6.5 `retrieve_router.py`：响应 `data` 增加 `query` 字段（返回原始 query）；`meta` 增加可选 `query_processing` 字段（有值或 null）
- [ ] 6.6 已有单元测试适配：`test_retrieve.py`、`test_retrieve_hybrid.py` — mock 返回值 `RewriteResult` → `QueryProcessResult`

## 7. 已有测试适配（RewriteResult 引用全部替换）

- [ ] 7.1 `test_rewrite_port.py`：完全重写，`RewriteResult` 测试 → `QueryProcessResult` 测试，加 `kb_context` 测试
- [ ] 7.2 `test_llm_rewrite.py`：所有 `RewriteResult` 引用 → `QueryProcessResult`，CacheEntry 类型断言更新
- [ ] 7.3 `test_noop_rewrite.py`：签名检查更新（返回类型 + kb_context 参数），返回值断言更新
- [ ] 7.4 `test_retrieve.py`：fixture mock 返回值字段映射
- [ ] 7.5 `test_retrieve_hybrid.py`：同上
- [ ] 7.6 `test_retrieve_full_chain.py`：检查并替换所有 `RewriteResult` 引用为 `QueryProcessResult`
- [ ] 7.7 `test_es_degradation.py`：同上

## 8. 前端调试台

- [ ] 8.1 `types/api.ts`：`RetrieveRequest` 增加 `query_options`，`RetrieveMeta` 增加 `query_processing`
- [ ] 8.2 `retrieve.tsx`：检索配置区增加「启用 query 改写」勾选框（含 HelpTooltip："用 AI 把口语问题改成更好搜的说法"）+ `query_options` 传参
- [ ] 8.3 `retrieve.tsx`：运行摘要区展示改写前后对比（原话、实际检索句、最终检索句、改写耗时、降级提示、扩展词列表）

## 9. 运维脚本

- [ ] 9.1 新增 `scripts/update_kb_settings.py`：`--kb-id` + `--settings-file` 必填，校验 kb_id 存在性，整文件覆盖 settings。打印 kb_id 和 synonyms 组数
- [ ] 9.2 新增 `scripts/generate_synonyms.py --kb-id KB_A`：遍历 KB 文档 chunks，调 LLM 提取专业术语并建议同义词，输出 `kb_settings.json`
- [ ] 9.3 新增 `examples/kb_settings.example.json`：含 synonyms 和可选 rewrite_hint

## 10. 外部脚本适配

- [ ] 10.1 `scripts/show_rewrite_quality.py`：`result.original_query` → `result.raw_query`，`result.rewritten_query` → `result.effective_query`，`result.needs_rewrite` 保留，`result.reason` → `result.degraded_reason`

## 11. 配置与文档

- [ ] 11.1 `.env.example` 补充 `QUERY_REWRITE_ENABLED=false` 和 `QUERY_REWRITE_TIMEOUT_MS=2000`
- [ ] 11.2 `retrieve_use_case.py` 读取 `QUERY_REWRITE_ENABLED` 环境变量作为全局默认，请求级 `query_options.enabled` 优先

## 12. 验收测试

- [ ] 12.1 不传 query_options + 无 settings → 行为与改前一致，`query_processing` 为 null，`data.query` 返回原话
```

Full source: openspec/changes/query-semantic-optimization/tasks.md

## openspec/changes/query-semantic-optimization/specs/query-processing-pipeline/spec.md

- Source: openspec/changes/query-semantic-optimization/specs/query-processing-pipeline/spec.md
- Lines: 1-80
- SHA256: 4c24b5ea684b4a0801d5a8759e409539ad7ea2be97cd049d350a1b4e105851cc

```md
# query-processing-pipeline

Pipeline 串联改写和词表扩展，填充完整的 `QueryProcessResult`。

## ADDED Requirements

### Requirement: QueryProcessResult 数据结构

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

`rewrite_latency_ms` 仅计 `rewrite()` 调用耗时。词表扩展耗时、检索耗时不计入。

#### Scenario: 改写耗时不计入检索延迟
- **GIVEN** 改写耗时 480ms, 检索耗时 150ms
- **WHEN** retrieve 完成
- **THEN** `query_processing.rewrite_latency_ms` ≈ 480
- **AND** `meta.latency_ms` ≈ 150
```

## openspec/changes/query-semantic-optimization/specs/query-rewrite-enhancement/spec.md

- Source: openspec/changes/query-semantic-optimization/specs/query-rewrite-enhancement/spec.md
- Lines: 1-59
- SHA256: 76f89dea1681570c229c58d544407e0c17eb30bdb6cdca87af3c2ecee5748e1b

```md
# query-rewrite-enhancement

LLM 改写增强：用 `QueryProcessResult` 统一改写输出，注入知识库上下文。

## MODIFIED Requirements

### Requirement: RewritePort 接口签名

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

`NoopRewriteProvider.rewrite()` 接受 `kb_context` 参数并忽略，返回 noop `QueryProcessResult`。

#### Scenario: Noop 返回 noop 结果
- **GIVEN** NoopRewriteProvider
- **WHEN** `rewrite(query="背调", kb_ids=["KB_A"], kb_context={...})`
- **THEN** 返回 `QueryProcessResult(raw_query="背调", effective_query="背调", search_query="背调", needs_rewrite=false, strategy="noop", degraded=false)`
```

## openspec/changes/query-semantic-optimization/specs/retrieve-api/spec.md

- Source: openspec/changes/query-semantic-optimization/specs/retrieve-api/spec.md
- Lines: 1-82
- SHA256: 6ee0db5eb6abcf71a2f047774e783cde23d2d145c7aa08d35bc3b3d4e629f2a8

[TRUNCATED]

```md
# retrieve-api (delta)

retrieve API 变更：请求新增 `query_options`，响应新增 `data.query` 和 `meta.query_processing`。

## MODIFIED Requirements

### Requirement: POST /v1/rag:retrieve 请求新增 query_options

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

响应 `meta` 新增可选字段 `query_processing`，类型为 `QueryProcessResult` 的 JSON 序列化：

```json
{
  "raw_query": "...",
  "effective_query": "...",
  "search_query": "...",
  "needs_rewrite": true,
  "strategy": "rewrite",
  "rewrite_latency_ms": 480,
  "degraded": false,
  "degraded_reason": null,
  "synonym_applied": true,
  "synonym_expansions": ["背景调查", "标准问题清单"]
}
```

#### Scenario: 有处理时返回完整链路
- **GIVEN** 开了改写且词表命中
- **THEN** `meta.query_processing` 包含上述所有字段

#### Scenario: 仅改写无词表
- **GIVEN** 开了改写但 KB 无 synonyms
- **THEN** `synonym_applied` = false, `synonym_expansions` = []
- **AND** `search_query` = `effective_query`

#### Scenario: 无处理时返回 null
```

Full source: openspec/changes/query-semantic-optimization/specs/retrieve-api/spec.md

## openspec/changes/query-semantic-optimization/specs/synonym-expansion/spec.md

- Source: openspec/changes/query-semantic-optimization/specs/synonym-expansion/spec.md
- Lines: 1-96
- SHA256: 46f97507af4ba576e225913654e300069d2b56f352f9e628d93f56e514ea0549

[TRUNCATED]

```md
# synonym-expansion

词表扩展：基于知识库级可配置词表，确定性追加扩展词到检索句。

## ADDED Requirements

### Requirement: 词表配置存储

`knowledge_bases.settings` JSONB 字段新增 `synonyms` 键，格式：

```json
{
  "synonyms": [
    {"terms": ["背调"], "expand": ["背景调查", "标准问题清单"]},
    {"terms": ["薪酬", "薪资", "工资"], "expand": ["职级", "薪酬定级", "定级标准"]}
  ]
}
```

#### Scenario: KB 有词表
- **GIVEN** KB_A.settings.synonyms 包含 2 组同义词
- **WHEN** 查询 KB_A 的 settings
- **THEN** 返回 2 组 synonyms

#### Scenario: KB 无词表
- **GIVEN** KB_B.settings 为 `{}` 或 `synonyms` 为空数组
- **WHEN** 词表扩展执行
- **THEN** `synonym_applied` = false, 无扩展词

### Requirement: 词表精确子串匹配

`SynonymExpander.expand(effective_query, synonyms)` → `(search_query, synonym_applied, expansions)`。中文精确子串匹配，英文忽略大小写。

#### Scenario: 单组命中
- **GIVEN** `synonyms = [{"terms": ["背调"], "expand": ["背景调查"]}]`
- **WHEN** `effective_query = "背调要问啥"`
- **THEN** `synonym_applied` = true
- **AND** `synonym_expansions` = ["背景调查"]
- **AND** `search_query` = "背调要问啥 背景调查"

#### Scenario: 多组同时命中，扩展词去重
- **GIVEN** 组1: `{"terms": ["背调"], "expand": ["背景调查", "清单"]}`, 组2: `{"terms": ["工资"], "expand": ["薪酬", "清单"]}`
- **WHEN** `effective_query = "背调和工资怎么谈"`
- **THEN** `synonym_expansions` 去重后 = ["背景调查", "清单", "薪酬"]

#### Scenario: 未命中
- **GIVEN** `synonyms = [{"terms": ["背调"], "expand": ["背景调查"]}]`
- **WHEN** `effective_query = "面试官行为规范"`
- **THEN** `synonym_applied` = false, `search_query` = `effective_query`

#### Scenario: 英文 term 忽略大小写
- **GIVEN** `synonyms = [{"terms": ["API"], "expand": ["接口"]}]`
- **WHEN** `effective_query = "api 文档在哪里"`
- **THEN** `synonym_applied` = true, `search_query` 含 "接口"

#### Scenario: synonyms 格式错误时容错
- **GIVEN** synonyms 为 `[{"terms": "背调"}]`（不是数组）
- **WHEN** 词表扩展执行
- **THEN** `synonym_applied` = false, 不抛异常

### Requirement: 跨库词表隔离

词表仅对当前 KB 生效，不跨库。

#### Scenario: KB_A 词表不影响 KB_B
- **GIVEN** KB_A 有 "背调" 扩展词, KB_B settings 为 `{}`
- **WHEN** 对 KB_B 检索 query="背调要问啥"
- **THEN** `synonym_applied` = false

## MODIFIED Requirements

### Requirement: KB settings CRUD

`KnowledgeBasePort` 新增两个方法：

```python
async def get_settings(self, kb_id: str) -> dict: ...
async def update_settings(self, kb_id: str, settings: dict) -> None: ...
```

```

Full source: openspec/changes/query-semantic-optimization/specs/synonym-expansion/spec.md

