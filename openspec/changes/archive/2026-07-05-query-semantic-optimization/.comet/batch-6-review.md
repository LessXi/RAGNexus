# 批次 6 审查报告：UseCase + Router + Composition 集成 (Stage 6)

审查范围：`retrieve_use_case.py`、`retrieve_router.py`、`composition.py`、`models.py`、`test_retrieve.py`、`test_retrieve_hybrid.py`

> 注：仓库当前文件已包含此前批次的累积变更（env var 读取、`effective_query` 字段等），本审查以**线上文件**为准，diff 作为辅助参考。

---

## 1. Spec Compliance

| # | 检查项 | 结论 | 证据 |
|---|--------|------|------|
| 1 | use_case 用 `pipeline.process()` 而非 `rewriter.rewrite()` | ✅ | `retrieve_use_case.py:140-158` 注入 `self._pipeline` 时走 `process()`；fallback 到 `rewriter.rewrite()`（159-164）作为兼容路径 |
| 2 | `kb_context` 从 `primary_kb` 正确组装（name, description, settings） | ⚠️ | `retrieve_use_case.py:108-120` 组装 name/description/rewrite_hint；但 `KnowledgeBase` 模型（`models.py:8-14`）**无 description 字段**，`getattr(primary_kb, "description", "")` 恒为空串 — 见 Finding 3 |
| 3 | synonyms 从 `kb_settings` 提取 | ✅ | `retrieve_use_case.py:117-120` 从 `kb_settings.get("synonyms")` 提取，符合 spec 格式 `[{"terms":..., "expand":...}]` |
| 4 | router 接受 `query_options`（enabled, strategy） | ✅ | `retrieve_router.py:19-23` 定义 `_QueryOptions`，`_RetrieveRequest:38` 增加可选字段；`extra: forbid` 阻止越界字段 |
| 5 | router 响应含 `data.query` + `meta.query_processing` | ⚠️ | `retrieve_router.py:119` `data.query`；`:122` `meta.query_processing` 字段存在；但 `_serialize_query_processing` 丢 `degraded_reason` — 见 Finding 4 |
| 6 | `query_processing` 无处理时返回 null | ✅ | `retrieve_router.py:111-114` 当 `strategy == "noop"` 且 `synonym_applied == False` 时返回 `None` |
| 7 | composition 正确注入 QueryPipeline | ✅ | `composition.py:335-349` 实例化 `SynonymExpander` + `QueryPipeline(rewriter, expander)` 注入 use_case |

**结论：7 项中 5 项通过，2 项部分通过（kb_context description 恒为空、query_processing 字段不完整）。**

---

## 2. Code Quality

### 2.1 KB 不存在时的处理
- KB 校验在 `retrieve_use_case.py:102-104` 已先于上下文组装执行：`if not await self._kb_repo.exists(kb_id): raise AppError(NOT_FOUND)`。
- `primary_kb = await self._kb_repo.get(kb_ids[0])` 后用 `if primary_kb:` 做空值保护（:112），`primary_kb` 为 None 时 `kb_context={}`、`synonyms=None`，pipeline 容错处理。✅ 正确。

### 2.2 环境变量 `QUERY_REWRITE_ENABLED` 读取
- `retrieve_use_case.py:142-143`：`os.getenv("QUERY_REWRITE_ENABLED", "false").lower() == "true"`，默认 `false`，仅 `"true"` 触发启用。✅ 读取正确。
- 顶部已 `import os`（:4）。

### 2.3 请求级 `enabled` 优先于环境变量
- ⚠️ **存在缺陷** — 见 Finding 1。

---

## 3. Findings

### Finding 1 [P1] — `_QueryOptions.enabled` 的 pydantic 默认值覆盖环境变量

**文件**：`src/ragnexus/adapters/http/retrieve_router.py:19-23` + `src/ragnexus/application/retrieve_use_case.py:145-148`

**Bug**：`_QueryOptions.enabled: bool = True` 是 pydantic 默认值。当客户端发送 `query_options` 但**未显式设置 enabled**（例如 `{"query_options": {"strategy": "rewrite"}}`），`model_dump()` 会产出 `{"enabled": True, "strategy": "rewrite"}`。use_case 中 `query_options.get("enabled", env_default)` 因此返回 `True`，**绕过 `QUERY_REWRITE_ENABLED=false` 的环境变量默认值**。

**触发条件**：环境变量 `QUERY_REWRITE_ENABLED=false`（默认），客户端请求 body 含 `query_options` 但不含 `enabled` 字段。

**影响**：运维通过环境变量全局关闭改写的意图被静默绕过；与 spec `retrieve-api/spec.md`「不传 query_options」场景「沿用全局默认」的语义不一致 —— 客户端「传了 query_options 但没传 enabled」被当作「显式启用」。

**修复建议**（任选其一）：

```python
# 方案 A：router 侧只 dump 客户端显式传入的字段（推荐）
query_options_dict = None
if req.query_options:
    query_options_dict = req.query_options.model_dump(exclude_defaults=True)
```

```python
# 方案 B：use_case 侧用哨兵判断是否显式传入
_ENABLED_UNSET = object()
explicit = query_options.get("enabled", _ENABLED_UNSET) if query_options else _ENABLED_UNSET
enabled = env_default if explicit is _ENABLED_UNSET else bool(explicit)
```

**confidence**: 0.95

---

### Finding 2 [P3] — `query_options.strategy` 字段被丢弃，无下游消费

**文件**：`src/ragnexus/adapters/http/retrieve_router.py:23, 94, 107`

**Bug**：`_QueryOptions.strategy` 被 pydantic 接收并 `model_dump()` 传给 `uc.execute(query_options=...)`，但 use_case 的 `enabled` 解析逻辑只读 `query_options.get("enabled", ...)`（`retrieve_use_case.py:145-148`），从未读取 `strategy`。`pipeline.process()` 签名也无 `strategy` 参数（`pipeline.py:32-39`）。

**影响**：客户端传 `strategy: "rewrite"` 或任何值都不会改变行为，可能误导调用方以为可控制策略。属于 dead-input，非阻断性。

**建议**：若 `strategy` 仅用于未来扩展，建议在 router 注释或 API 文档中明确标注「保留字段，当前未消费」；若应生效，则需要在 pipeline/use_case 中接入。本审查不要求立即实现 —— 标注为 P3。

**confidence**: 0.9

---

### Finding 3 [P2] — `kb_context.description` 恒为空，spec 场景无法满足

**文件**：`src/ragnexus/application/retrieve_use_case.py:115` + `src/ragnexus/domain/models.py:8-14`

**Bug**：use_case 用 `getattr(primary_kb, "description", "")` 取 description，但 `KnowledgeBase` dataclass 只有 `id / name / created_at / tenant_id / settings` 五个字段（`models.py:8-14`），**无 `description` 字段**。因此 `kb_context["description"]` 恒为空串。

**对 spec 的影响**：
- `design.md:88`「`kb_context` 包含 `name: str`、`description: str | None`、`rewrite_hint: str | None`」—— description 永远空。
- `query-rewrite-enhancement/spec.md:42-45` 场景「有完整 kb_context 时 prompt 包含上下文」（GIVEN `description="招聘、背调相关"`）**无法满足** —— LLM prompt 中「知识库描述: {desc}」分支（`llm.py:275-276`）因 `desc` 为空串 falsy 永不触发。
- Task 1.4（`tasks.md:6`）只给 `KnowledgeBase` 加了 `settings`，未加 `description`，是跨批次遗留缺口。

**触发条件**：任何启用了 pipeline 的检索请求，LLM 改写 prompt 都缺知识库描述上下文，改写质量低于 spec 预期。

**修复建议**（跨批次协调，本批次 use_case 代码本身是防御性的，不必单独修复）：

```python
# models.py — 为 KnowledgeBase 增加 description 字段
@dataclass
class KnowledgeBase:
    id: str
    name: str
    created_at: datetime
    tenant_id: str = ""
    description: str = ""              # 新增
    settings: dict = field(default_factory=dict)
```
并在 PgKnowledgeBaseRepository 的 `get()` SQL 中 select `description`。

**confidence**: 0.85

---

### Finding 4 [P2] — `_serialize_query_processing` 丢弃 `degraded_reason`，pipeline 降级原因丢失

**文件**：`src/ragnexus/application/retrieve_use_case.py:352-364`

**Bug**：`QueryProcessResult` 有 10 个字段（`ports.py:144-169`），`_serialize_query_processing` 输出 9 个，**唯独漏掉 `degraded_reason`**：

```python
return {
    "raw_query": result.raw_query,
    "effective_query": result.effective_query,
    "search_query": result.search_query,
    "needs_rewrite": result.needs_rewrite,
    "strategy": result.strategy,
    "rewrite_latency_ms": result.rewrite_latency_ms,
    "degraded": result.degraded,        # ← 有 degraded
    # degraded_reason 丢失
    "synonym_applied": result.synonym_applied,
    "synonym_expansions": result.synonym_expansions,
}
```

**对 spec 的影响**：
- `retrieve-api/spec.md:54-68` 明确响应 `meta.query_processing` 是「`QueryProcessResult` 的 JSON 序列化」，示例 JSON 中含 `"degraded_reason": null`（:65）。
- `design.md:129-140` 响应示例同样含 `degraded_reason`（:137）。
- `query-processing-pipeline/spec.md:18-19` 与 `:28` 明确 `degraded_reason` 是 `QueryProcessResult` 的契约字段。
- 实际响应缺少该字段 → **响应结构与文档化契约不符**。

**触发条件**：pipeline 降级时（`rewriter.rewrite()` 抛异常，`pipeline.py:73-86` 构造 `degraded=True, degraded_reason=str(exc)`），客户端能看到 `degraded=true` 但无法得知原因。

**额外影响**：顶层 `RetrieveResult.degraded_reason`（`models.py`）仅承载 ES 不可用降级（`retrieve_use_case.py:124-128`），**不承载 pipeline 降级**。因此 pipeline 降级原因的唯一来源就是 `query_processing.degraded_reason`，被序列化器丢弃后客户端**完全没有**途径获知 pipeline 为何降级 —— 这是可观测性缺口，不是单纯的字段遗漏。

**修复建议**：

```python
def _serialize_query_processing(result: QueryProcessResult) -> dict:
    """将 QueryProcessResult 序列化为 query_processing dict。"""
    return {
        "raw_query": result.raw_query,
        "effective_query": result.effective_query,
        "search_query": result.search_query,
        "needs_rewrite": result.needs_rewrite,
        "strategy": result.strategy,
        "rewrite_latency_ms": result.rewrite_latency_ms,
        "degraded": result.degraded,
        "degraded_reason": result.degraded_reason,   # 补回
        "synonym_applied": result.synonym_applied,
        "synonym_expansions": result.synonym_expansions,
    }
```

**confidence**: 0.95

---

## 4. 测试覆盖评估

- `test_retrieve.py` + `test_retrieve_hybrid.py` 已全面将 `mock_rewriter` fixture 替换为 `mock_pipeline`，`RewriteResult` → `QueryProcessResult`，`rewrite.side_effect` → `process.side_effect`，参数从 `(query, kb_ids)` 改为 `(raw_query, kb_ids, kb_context, synonyms, enabled)`。
- 覆盖了：pipeline 在 embed 前调用、`search_query` 用于 embed、rerank 用原始 query、Noop pipeline 直通集成。
- `mock_kb_repo.get.return_value = None` 的设置覆盖了「primary_kb 不存在」防御路径。✅
- **缺口**：未发现针对「`query_options` 显式 enabled=True 覆盖 env_default=False」或「`query_options` 缺 enabled 时 fallback 到 env_default」的测试 —— 与 Finding 1 直接相关，建议补测。
- **缺口**：未发现 router 层 `_QueryOptions` 的 pydantic 行为测试（`test_http_schema_invariance.py` 依赖该 router，但未覆盖 query_options 默认值边界）。
- **缺口**：未发现针对 `_serialize_query_processing` 字段完整性的断言测试（Finding 4）—— 现有 mock_pipeline 的 `_passthrough` 返回 `degraded_reason=None` 但无测试断言响应 `query_processing` 包含该字段，缺陷因此未被捕获。
- **缺口**：未发现针对 pipeline 降级路径（rewrite 抛异常 → `degraded=True` + `degraded_reason` 透传到响应）的端到端断言。

---

## 5. 总评

`overall_correctness`: **incorrect**

批次 6 的主体集成（pipeline 接入、kb_context/synonyms 组装、router 字段、composition 注入）实现完整且符合 spec 大方向，测试 fixture 适配到位。但存在以下需在合入前处理的缺陷：

1. **P1 - Finding 1**：`_QueryOptions.enabled` 的 pydantic 默认值 `True` 静默绕过 `QUERY_REWRITE_ENABLED=false` 环境变量，与 spec「不传 query_options 沿用全局默认」语义冲突，且无对应测试覆盖。
2. **P2 - Finding 3**：`KnowledgeBase` 模型缺 `description` 字段（跨批次遗留），导致 `kb_context.description` 恒为空，spec 场景「prompt 包含知识库描述」不可达。
3. **P2 - Finding 4**：`_serialize_query_processing` 丢弃 `degraded_reason`，响应结构与 spec 契约不符；叠加顶层 `RetrieveResult.degraded_reason` 不承载 pipeline 降级，pipeline 降级原因对客户端完全不可观测。

建议合入前修复 Finding 1 与 Finding 4（本批次内可完成），Finding 3 需跨批次协调补 `KnowledgeBase.description` 字段及 repository SQL。Finding 2 为保留字段标注问题，P3 可后续处理。

`confidence`: 0.9
