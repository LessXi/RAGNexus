# Comet Design Handoff

- Change: kb-retrieve-pages
- Phase: design
- Mode: compact
- Context hash: 55cb5faddf3aafb489b74452fe8fc6d983ab07d4e575ed77d5f1bb7af23f894c

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/kb-retrieve-pages/proposal.md

- Source: openspec/changes/kb-retrieve-pages/proposal.md
- Lines: 1-37
- SHA256: ae00b2b3b91fa0ac309692c22b3e736a9b68128e6b23a6b71c3a186700afb8f6

```md
## Why

RAGNexus 调试台目前只有上传页（`/`）。用户上传文档后存在两个明显痛点：

1. **关掉浏览器就找不回建好的知识库** — 没有列表页展示已有数据，无法跨会话/跨设备查看
2. **无法直观验证检索召回效果** — 不知道某条 query 召回哪些 chunk、分数如何

需要新增两个页面解决这两个问题，同时抽公共顶栏组件。

## What Changes

### 数据库
- `knowledge_bases` 表新增 `tenant_id TEXT NOT NULL` 列（**BREAKING**：存量 KB 统一标记 `'default'`）

### 后端 API
- **新增** `GET /api/v1/knowledge-bases/tree` — 租户→知识库→文档三级树
- **改造** `POST /api/v1/rag/retrieve` — 支持 mode 切换、hybrid 参数、per-chunk 分数、latency_ms
- **扩展** `POST /api/v1/knowledge-bases:create` — 新增 `tenant_id` 必填字段（**BREAKING**）

### 前端
- 新增 `AppHeader` 公共顶栏组件，替换旧侧栏 `Layout`
- 新增 `/knowledge-bases` 列表页（KnowledgeFileTreePage）
- 新增 `/retrieve` 检索调试页（RetrievePage）
- 重构 `/` 首页：合并创建 KB 表单 + 上传文档区域
- 去掉 localStorage KB 缓存，改用 tree API
- 白色科技风样式（shadcn/ui + Tailwind）

## Capabilities

### New Capabilities
- `knowledge-base-tree`: 租户→知识库→文档三级树查询与展示
- `retrieve-debug`: 检索调试页，支持多模式、per-stage 分数、运行摘要
- `app-header`: 公共顶栏组件，替代旧侧栏布局

### Modified Capabilities
- `document-upload`: 首页合并创建 KB 表单（原 CreateKBPage 移除）
- `rag-retrieve`: 接口增强，支持 mode 参数和 per-hit 分数（向后兼容）
```

## openspec/changes/kb-retrieve-pages/design.md

- Source: openspec/changes/kb-retrieve-pages/design.md
- Lines: 1-103
- SHA256: c1700cff1ed5aeb74188e01cb1a702bbf83a49fb4773eaad730c799137d2e8a8

[TRUNCATED]

```md
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
```

Full source: openspec/changes/kb-retrieve-pages/design.md

## openspec/changes/kb-retrieve-pages/tasks.md

- Source: openspec/changes/kb-retrieve-pages/tasks.md
- Lines: 1-66
- SHA256: aa111a544acf4ad75d60320a2e2585ca1004ce0f3bb3d04596855e20e4fb3e50

```md
## 1. Database Migration

- [ ] 1.1 创建 Alembic migration `0002_add_tenant_id.py`：`knowledge_bases` 新增 `tenant_id TEXT NOT NULL DEFAULT 'default'`，`name_key` 唯一约束改为 `(tenant_id, name_key)` 联合唯一
- [ ] 1.2 更新 `PgKnowledgeBaseRepository.create()` 接受并写入 `tenant_id`，冲突检测改为联合唯一
- [ ] 1.3 更新 `KnowledgeBasePort.create()` 协议签名（加 `tenant_id` 参数）
- [ ] 1.4 更新 `CreateKnowledgeBaseUseCase.execute()` 接受 `tenant_id`，校验 1–64 字符
- [ ] 1.5 更新 `create_kb_router.py`：请求体加 `tenant_id`，响应加 `tenant_id`
- [ ] 1.6 更新 `demo_retrieve.py` 和受影响的测试（create KB 调用加 `tenant_id`）

## 2. Retrieve 链路改造（per-chunk 分数 + RetrieveResult）

- [ ] 2.1 `models.py` 新增 `RetrieveResult` dataclass（hits + meta 字段，含 `degraded_reason`）
- [ ] 2.2 `retrieve_use_case.py`：向量和 BM25 召回后，立即标记 `_vector_score` / `_bm25_score` 到各自 hit.metadata
- [ ] 2.3 `fusion.py` 改造 `rrf_fuse`：合并两路 `_vector_score` / `_bm25_score`（在 2.2 标记完成后进行）
- [ ] 2.4 `retrieve_use_case.py`：`execute()` 签名扩展——接受 `mode`、`candidate_k`（由 `vector_top_k`/`bm25_top_k` 映射）、`rrf_k`、`rerank_enabled`、`rerank_top_n`
- [ ] 2.5 `retrieve_use_case.py`：返回值改为 `RetrieveResult`，打包 hits + 运行元信息
- [ ] 2.6 `rerank/llm.py`：在 `_merge_and_sort` 返回前，将内部 `chunk_scores` 写入每个 hit 的 `metadata["_rerank_score"]`

## 3. Retrieve API（请求/响应 schema 升级）

- [ ] 3.1 `retrieve_router.py`：`_RetrieveRequest` 扩展——`mode`、`vector_top_k`、`bm25_top_k`、`rrf_k`、`rerank` 嵌套对象
- [ ] 3.2 `retrieve_router.py`：响应序列化——提取 `_` 前缀字段到 per-hit 顶层字段，构建 `meta` 块（含 `total`、`latency_ms`、`degraded_reason`）
- [ ] 3.3 `retrieve_router.py`：router 内部适配 `RetrieveResult` 新返回类型（composition.py 装配不变，router factory 自包含）
## 4. Tree API（新增）

- [ ] 4.1 `KnowledgeBasePort` 新增 `list_with_documents(keyword: str | None)` 方法签名
- [ ] 4.2 `PgKnowledgeBaseRepository` 实现 `list_with_documents()`——JOIN knowledge_bases + documents，组装三级树
- [ ] 4.3 新建 `GetKnowledgeBaseTreeUseCase`，委托 repo
- [ ] 4.4 新建 `GET /api/v1/knowledge-bases/tree` router，含 `keyword` query 参数
- [ ] 4.5 `composition.py` 注册新 router 和 use case

## 5. 前端：AppHeader + 路由重组

- [ ] 5.0 安装 shadcn/ui Table 组件：`npx shadcn add table`（列表页和检索结果页依赖）
- [ ] 5.1 新建 `AppHeader` 组件（白色科技风、52px、sticky、左侧品牌名，参考 ui-design-mockup.html）
- [ ] 5.2 重写 `Layout` 为 `AppHeader + Outlet` 结构，去掉侧栏
- [ ] 5.3 `App.tsx` 路由表：`/` → UploadDocPage、`/knowledge-bases` → KnowledgeFileTreePage、`/retrieve` → RetrievePage
- [ ] 5.4 删除旧的 `create-kb.tsx` 页面文件（功能已合并到 UploadDocPage）

- [ ] 6.1 `UploadDocPage` 顶部新增「创建知识库」Card（tenant_id + name + 按钮）
- [ ] 6.2 创建 KB 后更新本地下拉选项（从 tree API 刷新）
- [ ] 6.3 KB 下拉数据源从 localStorage → tree API 调用
- [ ] 6.4 去掉 `storage.ts` 的 localStorage 逻辑

## 7. 前端：知识库列表页

- [ ] 7.1 新建 `KnowledgeFileTreePage`——调用 tree API，渲染三级可展开树
- [ ] 7.2 搜索框：按 tenant_id 模糊过滤
- [ ] 7.3 KB 行操作按钮：复制 kb_id、跳转上传（带 kb_id）、跳转检索（带 query params）
- [ ] 7.4 空状态和加载态

## 8. 前端：检索调试页

- [ ] 8.1 新建 `RetrievePage`——检索配置（可折叠）+ 检索召回 + 运行摘要三 Card
- [ ] 8.2 检索配置：租户/KB 选择、top_k、mode tabs、hybrid 参数（条件显示）、rerank toggle
- [ ] 8.3 URL query params 预填（从列表页跳转带入 tenant_id + kb_id）
- [ ] 8.4 检索执行 + 结果渲染（per-hit 分数 chips、文档内容可折叠）
- [ ] 8.5 运行摘要 Card（meta 字段展示）
- [ ] 8.6 表单校验 + 加载态 + 错误态

## 9. 联调 & 验收

- [ ] 9.1 全量后端单元测试通过（含 rrf_fuse 新逻辑）
- [ ] 9.2 全量前端 unit test 通过
- [ ] 9.3 E2E：14 条全链路验收（docs/acceptance-criteria.md 第四节）
- [ ] 9.4 回归：首页上传逻辑不受影响
```

