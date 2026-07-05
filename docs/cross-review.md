# 对抗性交叉评审报告

## 评审范围

- `openspec/changes/kb-retrieve-pages/` (proposal, design, tasks)
- `docs/api-spec.md`
- `docs/acceptance-criteria.md`
- `admin/public/ui-design-mockup.html`

以现有代码为准绳，逐文档逐行交叉比对。

---

## 🔴 严重问题（阻塞实现）

### 1. `_rerank_score` 写入路径缺失

**位置**：design D2、tasks 2.6、api-spec 响应 schema

**问题**：tasks 2.6 说「`rerank/llm.py`：重排后将 `_rerank_score` 写入 hit metadata」。但 LLMRerankProvider 的 rerank 分存在**局部变量**中（`matched_rankings`、`llm_rankings`），`_merge_and_sort` 方法内部计算了 `chunk_scores` 但不写回 SearchHit。返回值 `score` 字段保持向量原始分。当前代码**没有任何路径暴露 rerank 分值**。

**代价**：实现时需要在 `_merge_and_sort` 的返回前遍历 hits，写入 `metadata["_rerank_score"] = chunk_scores[cid]`。大约 3 行代码，但必须改 LLMRerankProvider 的内部方法。

**建议**：修正 tasks 2.6 描述为「`rerank/llm.py`：在 `_merge_and_sort` 返回前，将 `chunk_scores` 写入每个 hit 的 `metadata["_rerank_score"]`」。

### 2. BM25 仅搜索第一个 KB，其余 kb_id 被忽略

**位置**：design D4、api-spec 检索参数、acceptance AC3.1

**问题**：`KeywordSearchPort.search_by_keyword(kb_id: str, ...)` 只接受**单个** kb_id。hybrid 模式下检索代码 `kb_ids[0]` 硬编码取第一个。这意味着：
- API 允许 `kb_ids: ["kb_A", "kb_B"]`
- 向量检索两个 KB 都搜
- BM25 只搜 kb_A
- 用户看不到 kb_B 的 BM25 结果，但 RRF 融合后结果可能**缺少** kb_B 的 chunk

**影响**：不是 bug（现有行为如此），但设计文档和 API spec 完全没有提及这个限制。调试页面用户传多个 kb_id 时，BM25 结果不完整。

**建议**：在 design 文档的 D4 旁加注 `⚠️ 已知限制：BM25 仅搜索 kb_ids[0]，多 KB 时关键词召回不完整`。

### 3. name_key 约束跨租户唯一

**位置**：design D1、api-spec 创建 KB、acceptance AC1.2

**问题**：`knowledge_bases.name_key` 有数据库唯一约束。用户想在不同租户下创建同名的 KB 会失败（如 tenant_A 和 tenant_B 各建一个「演示库」，name_key 都是 `演示库`）。

**影响**：与 PRD 的「多租户分组」理念冲突。不同租户应能创建同名 KB。修复需要 migration 改约束为 `(tenant_id, name_key)` 联合唯一。

**建议**：立即决定：① 接受此限制（文档注明）或 ② 改唯一约束。我的判断是调试工具接受即可，但 design 文档必须写明。

---

## 🟡 中等问题（影响实现顺序或测试）

### 4. `total` 字段移动未在 api-spec 中说明

api-spec 的 retrieve 响应把 `total` 去掉了（现有响应有 `data.total`，新响应没有），但 acceptance 和 tasks 都没提这个 breaking change。建议在 api-spec 的 meta 块加 `total: 5`，明确 `total` 下沉到 `meta`。

### 5. tasks 缺少「更新 demo_retrieve.py」

`demo_retrieve.py` 直接调用 `retrieve_uc.execute(query=..., kb_ids=..., top_k=...)`。签名变化后它必须更新。tasks 1.6 的「更新受影响的测试和 demo 脚本」只放在 DB migration 组，不覆盖 Retrieve 链路的变化。

### 6. 缺少 `npx shadcn add table` 前置任务

`admin/src/components/ui/` 目录为空，没有任何 shadcn 组件。列表页和检索结果页都需要 Table/DataTable。tasks 未提。

### 7. `degraded_reason` 字段缺失

api-spec 的 meta 定义了 `degraded_reason: string | null`，但 design D3 的 RetrieveResult 只有 `degraded: bool`。router 序列化时会缺少此字段。

### 8. route 命名风格不一致

现有路由全部用 `:action` 后缀：`/v1/knowledge-bases:create`、`/v1/documents:upload`、`/v1/rag:retrieve`。新 tree API 用 `/v1/knowledge-bases/tree`，打破了约定。建议统一为 `GET /v1/knowledge-bases:tree`。

### 9. 验收计数不准

acceptance-criteria.md 标题写「43 单元 + 14 E2E」，实际数出来是 58 条场景（AC1:6 + AC2:9 + AC3:13 + AC4:2 + AC5:6 + AC6:8 + AC7:10 + AC8:4 = 58）。

---

## 🟢 建议改进

### 10. UI mockup 与实际技术栈有差距

mockup 使用 inline SVG 和自定义 CSS，但实际项目用 `lucide-react` + Tailwind + shadcn/ui。实现时外观会不同——不是问题，但团队需理解 mockup 是**视觉方向参考**，非像素级蓝图。

### 11. tasks 未明确 migration 文件名

task 1.1 只说「创建 Alembic migration」，但现有 migration 是 `0001_initial_schema.py`。约定下一版应为 `0002_add_tenant_id.py` 或类似命名。

### 12. 设计 D5 中 `null` vs `不写入` 语义模糊

D5 说「`_bm25_score` = null（不写入）」。实现时 router 提取逻辑需要区分「key 不存在」和「key 值为 null」。建议统一：始终写入，不可用时值为 `null`（JSON null），这样 router 的序列化逻辑最简单。

---

## 修复清单（按优先级）

| # | 修复 | 影响文件 |
|---|---|---|
| P0 | 澄清 `_rerank_score` 写入路径 | tasks 2.6 |
| P0 | 注明 BM25 单 KB 限制 | design D4, api-spec |
| P0 | 决定 name_key 约束策略（注记 or 改约束） | design D1 |
| P1 | meta 加 `total` 字段 | api-spec |
| P1 | 新增「更新 demo_retrieve.py」任务 | tasks §2 |
| P1 | 新增加 `shadcn table` 前置任务 | tasks §5 |
| P1 | RetrieveResult 加 `degraded_reason` | design D3, api-spec |
| P1 | 统一路由风格为 `:tree` | api-spec, tasks 4.4 |
| P2 | 修正验收计数（58 条） | acceptance-criteria |
| P2 | 统一 metadata 缺失值策略为「始终写入 null」 | design D5 |
| P2 | 明确 migration 文件名 | tasks 1.1 |
