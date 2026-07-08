## Context

RAGNexus 是一个 RAG 中台调试工具，现有架构：

- **后端**：FastAPI + asyncpg + pgvector + Elasticsearch，Clean Architecture（domain/application/adapters）
- **前端**：React 18 + Vite + shadcn/ui + Tailwind + React Router v6，当前只有侧栏布局 + 一个上传页
- **检索链路**：query → rewrite → embed → vector search + BM25 → RRF fuse → rerank → hits

本次为系统新增「知识库列表」和「检索调试」两个页面，同时升级检索 API 使其参数可控、结果可观测。

## Goals / Non-Goals

**Goals:**
- 新增 `/knowledge-bases` 列表页，三层树形展示租户→KB→文档
- 新增 `/retrieve` 检索调试页，可视化召回分数和运行摘要
- 检索 API 支持前端动态控制 mode、hybrid 参数、rerank
- 检索 API 返回 per-hit 分阶段分数和 latency_ms
- 引入 tenant_id 维度对 KB 分组
- 重构前端布局：侧栏换顶栏，去掉 localStorage

**Non-Goals:**
- 不做鉴权、不做分页、不做删除
- 不建 tenants 独立表
- 不扩展 SearchHit 领域模型字段（分数通过 metadata 透传）
- 不改 chunk 表结构

## Decisions

### D1: tenant_id 存储在 knowledge_bases 列中

**选**：`knowledge_bases` 新增 `tenant_id TEXT NOT NULL` 列，创建时用户填写。同时将 `name_key` 唯一约束改为 `(tenant_id, name_key)` 联合唯一——不同租户可创建同名 KB。
**弃**：不建独立 `tenants` 表——调试工具不做租户管理，列足够。

### D2: per-chunk 分数通过 SearchHit.metadata 透传

**选**：不改 `SearchHit` 领域模型。Use Case 内部在 `metadata` 中写入 `_vector_score`、`_bm25_score`、`_rerank_score`（`_` 前缀表示内部字段），Router 序列化时提取并删除。

**替代方案**：扩展 `SearchHit` 加 `vector_score`/`bm25_score`/`rerank_score` 字段。弃用原因：36 处引用需修改，且调试页面特有的展示需求不应膨胀领域模型。

### D3: RetrieveUseCase 返回 RetrieveResult 而非 list[SearchHit]

**选**：新增 `RetrieveResult` dataclass，包含 `hits: list[SearchHit]` + `latency_ms`、`mode`、`vector_count`、`bm25_count`、`fused_count`、`rerank_model`、`degraded`、`degraded_reason`。

**替代方案**：在 metadata 里塞这些元信息。弃用原因：混淆 hit 级别和请求级别的数据。

### D4: candidate_k 拆分映射

请求体 `vector_top_k` 和 `bm25_top_k` 分开传入。Use Case 内部：
- hybrid 模式：向量用 `vector_top_k`，BM25 用 `bm25_top_k`
- vector/bm25 单模式：各自直接用 `top_k`（忽略 `*_top_k` 参数）

不传 `*_top_k` 时回退到 composition.py 中配置的 `candidate_k` 默认值。

⚠️ **已知限制**：`KeywordSearchPort.search_by_keyword` 只接受单个 `kb_id`。hybrid 模式下 BM25 仅搜索 `kb_ids[0]`，其余 KB 只有向量召回结果。调试页面的主流场景（从列表页点检索）只带一个 kb_id，影响极小。

### D5: rrf_fuse 改造——保留两路原始分

现有 `rrf_fuse` 从两路 hit 构造新 SearchHit 时只保留一个来源的 metadata（先到先得）。需要改造为合并两路的 `_vector_score`/`_bm25_score`：
- 仅向量来源：`_vector_score` = 该 hit.score，`_bm25_score` = null
- 仅 BM25 来源：`_vector_score` = null，`_bm25_score` = 该 hit.score
- 两路共有：两个分数都保留

`_` 前缀字段始终写入 metadata（不可用时值为 JSON null），便于 router 统一提取。

### D6: 前端布局：侧栏 → AppHeader 顶栏

旧 `Layout` 组件的 `<aside>` 侧栏替换为 `<header>` 顶栏组件 `AppHeader`。三页面通过 React Router `<Routes>` 共享同一个 Layout（AppHeader + `<Outlet/>`）。右侧无导航入口（页面间通过 Tab 栏或 URL 跳转）。

路由表：

| 路由 | 组件 | 说明 |
|---|---|---|
| `/` | UploadDocPage（含创建 KB） | 首页 |
| `/knowledge-bases` | KnowledgeFileTreePage | 列表页 |
| `/retrieve` | RetrievePage | 检索调试 |

### D7: 去掉 localStorage

旧代码 `getKBs()` 从 localStorage 读 KB 列表。改为 `fetchTree()` 从 `/api/v1/knowledge-bases/tree` 获取。`upload-doc.tsx` 的 KB 下拉选项来源从 localStorage 改为 API。
## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| `rrf_fuse` 改造影响已有测试（19 tests） | 先跑全量测试，改造后增量修复 |
| `tenant_id` migration 存量数据全部 `'default'`，`name_key` 约束改为联合唯一 | 调试工具，存量数据可接受；联合唯一是增量 migration |
| 检索 API 响应结构变化（新增 `meta` 块） | `meta` 是新增字段，不影响旧 `data.hits` 结构 |
| `POST /v1/knowledge-bases:create` 新增必填 `tenant_id` | demo 脚本和已有测试需同步更新 |
| BM25 仅搜第一个 kb_id | 调试页面主流场景单 KB，文档注明限制 |

## Implementation Order

1. Migration（tenant_id 列 + `(tenant_id, name_key)` 联合唯一约束）
2. 立刻更新 Create KB 链路（repo → port → use case → router），防止 migration 后报错
3. rrf_fuse 改造 + per-chunk 分数标记（先标记再融合）
4. RetrieveUseCase 新签名 + RetrieveResult
5. Retrieve router 请求/响应 schema 升级
6. PgKnowledgeBaseRepository.list_with_documents()
7. Tree API use case + router
8. 前端：AppHeader + 路由重组
9. 前端：首页合并（创建 KB + 上传）
10. 前端：KnowledgeFileTreePage
11. 前端：RetrievePage
12. 前端：去 localStorage，联调
