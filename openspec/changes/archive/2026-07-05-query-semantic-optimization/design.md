## Context

RAGNexus 已有 LLM 改写基础设施（`RewritePort` 协议、`LLMRewriteProvider`、`NoopRewriteProvider`），在 `retrieve_use_case.py` 中接入检索链路。当前改写输出 `RewriteResult`（4 字段：`original_query`、`rewritten_query`、`needs_rewrite`、`reason`），LLM 自行判断是否需要改写，改写时不知晓知识库领域上下文。

本次变更的架构主轴：**删除 `RewriteResult`，统一用 `QueryProcessResult`（10 字段）替代。** 这样改写器直接输出完整结果，pipeline 只需补充 synonym 字段，不需要映射层。

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
        *,
        query: str,
        kb_ids: list[str],
        kb_context: dict | None = None,  # 新增
    ) -> QueryProcessResult: ...          # 返回类型变更
```

`kb_context` 包含 `name: str`、`description: str | None`、`rewrite_hint: str | None`。

### 5. KB settings 存储：JSONB

**决策**：`knowledge_bases.settings JSONB NOT NULL DEFAULT '{}'`。

```json
{
  "synonyms": [
    {"terms": ["背调"], "expand": ["背景调查", "标准问题清单"]}
  ],
  "rewrite_hint": "可选，补充给 LLM 的领域说明"
}
```

### 6. 词表初始种子：LLM 自动生成

`scripts/generate_synonyms.py --kb-id KB_A`：遍历 KB 文档 chunks，调 LLM 提取专业术语并建议同义词，输出 `kb_settings.json`。管理员审核后通过 `update_kb_settings.py` 上传。

### 7. API Schema

**请求**：
```json
{
  "query": "背调要问啥",
  "kb_ids": ["KB_A"],
  "query_options": { "enabled": true, "strategy": "rewrite" }
}
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "query": "背调要问啥",
    "hits": [...],
    "meta": {
      "latency_ms": 150.0,
      "mode": "hybrid",
      ...
      "query_processing": {
        "raw_query": "背调要问啥",
        "effective_query": "背景调查标准问题有哪些",
        "search_query": "背景调查标准问题有哪些 背景调查 标准问题清单",
        "needs_rewrite": true,
        "strategy": "rewrite",
        "rewrite_latency_ms": 480,
        "degraded": false,
        "degraded_reason": null,
        "synonym_applied": true,
        "synonym_expansions": ["背景调查", "标准问题清单"]
      }
    }
  }
}
```

**`query_processing` 何时为 null**：不传 `query_options` 且 KB 无 settings 时，`query_processing` 为 `null`，与改前完全兼容。

**已知偏离**：验收测试文档中默认行为返回 `query_processing: { enabled: false, strategy: "noop", ... }`。我们的设计选择返回 `null`，以保持更干净的向后兼容——旧客户端不会看到新增字段。这是有意偏离，不是疏忽。

**`data.query`**：始终返回用户原始 query，不因改写而变。这是新增字段（当前 API 响应中不存在）。

**`enabled` 与 `strategy` 的关系**：`enabled=false` 时忽略 `strategy`。`enabled=true` 时 `strategy` 决定改写策略（当前仅 `"rewrite"`）。

### 8. Pipeline 中的降级处理

`QueryPipeline.process()` 调用 `rewrite()` 时：
- `rewrite()` 抛异常 → Pipeline 捕获，构造 `QueryProcessResult`：`degraded=true`, `effective_query=raw_query`, `needs_rewrite=false`
- `rewrite()` 正常返回但 LLM 内部降级 → `degraded` 已由改写器设置，Pipeline 直接透传

词表扩展阶段不抛异常——格式错误的 synonyms 静默跳过。

## Data Flow

```
POST /v1/rag:retrieve { query, kb_ids, query_options? }
  │
  ▼ retrieve_router.py: 解析 query_options
  │
  ▼ retrieve_use_case.py: 查出 kb → { name, description, settings }
  │
  ▼ QueryPipeline.process(raw_query, kb_context, settings.synonyms, enabled)
  │
  │  ┌─ [if enabled] RewritePort.rewrite(query, kb_ids, kb_context)
  │  │    └─ 返回 QueryProcessResult { raw_query, effective_query, needs_rewrite,
  │  │       degraded, rewrite_latency_ms, ... }
  │  │
  │  ├─ [if enabled && synonyms] SynonymExpander.expand(effective_query, synonyms)
  │  │    └─ 填充 search_query, synonym_applied, synonym_expansions
  │  │
  │  └─ 返回完整 QueryProcessResult
  │
  ▼ 用 search_query 做 vector / bm25 / hybrid 检索
  │
  ▼ 响应: { data: { query: raw_query, hits: [...], meta: { query_processing } } }
```

## Architecture

```
src/ragnexus/adapters/rewrite/
├── llm.py                 # MOD: RewriteResult → QueryProcessResult + kb_context 注入
├── noop.py                # MOD: 同上 + 接 kb_context
├── synonym_expander.py    # NEW: SynonymExpander 类
├── pipeline.py            # NEW: QueryPipeline 类
```

## Field Mapping: RewriteResult → QueryProcessResult

改写器内部所有 `RewriteResult(...)` 构造替换为：

```python
QueryProcessResult(
    raw_query=         original_query,     # 字段重命名
    effective_query=   rewritten_query,    # 字段重命名
    search_query=      rewritten_query,    # 默认 = effective，后续由 pipeline 覆盖
    needs_rewrite=     needs_rewrite,      # 保留
    strategy=          "rewrite" | "noop",
    rewrite_latency_ms=latency_ms,        # 新增：改写器内部计时
    degraded=          True（降级时）| False,
    degraded_reason=   reason（仅降级）| None,
    synonym_applied=   False,              # 默认值
    synonym_expansions=[],                 # 默认值
)
```

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| `RewriteResult` 删除导致全代码库 8+ 文件改动 | 按依赖拓扑分层修改，每层有单元测试守卫 |
| `QueryProcessResult` 10 字段，改写器只填一部分，pipeline 补另一部分——状态一致性靠约定 | 字段有明确默认值；改写器不填 synonym 字段，pipeline 不覆盖 rewrite 字段。写清楚谁填什么 |
| `kb_context` 多 KB 时传哪个？ | 取 `kb_ids[0]` 对应的 KB 上下文；多 KB 且 description 不同时，LLM 只看到第一个 KB 的上下文。文档注明此限制 |
| 词表扩展拼接可能影响 vector 检索质量 | 受 `enabled` 控制；后续 A/B 测试验证 |
| `rewrite_hint` 写错误导 LLM | 文档标注"多数情况不需要" |
| KB settings JSONB 无 schema 校验 | 运维脚本做格式校验；运行时容错 |
| 词表数据来源未自动化 | `generate_synonyms.py` 提供初始种子；后续基于 `retrieve_logs` 自动建议 |

## Migration Plan

1. Alembic migration：`knowledge_bases.settings JSONB NOT NULL DEFAULT '{}'`
2. 部署顺序：先跑 migration → 再部署新代码
3. 回滚：settings 列有默认值，回滚代码不影响已有请求
4. 兼容性：旧客户端不传 `query_options` → `query_processing` 为 null，行为与改前一致
