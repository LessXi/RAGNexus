---
change: kb-retrieve-pages
design-doc: docs/superpowers/specs/2026-07-04-kb-retrieve-pages-design.md
base-ref: 36e2af511ec2e95f47211a9e2b9c9ae0b893d03e
archived-with: 2026-07-04-kb-retrieve-pages
---

# KB List + Retrieve Debug 实施计划

> **对于 agentic workers:** 使用 superpowers:subagent-driven-development 逐任务执行。步骤使用 checkbox (`- [ ]`) 跟踪。

**目标:** 在 RAGNexus 调试台新增知识库列表页 + 检索调试页 + 公共 AppHeader 组件

**架构:** FastAPI Clean Architecture (domain/application/adapters) + React shadcn/ui 前端

**技术栈:** Python 3.11 + FastAPI + asyncpg + pgvector + Elasticsearch | TypeScript + React 18 + Tailwind + shadcn/ui + Vite

## 全局约束

- 后端遵循 Clean Architecture: domain models → ports → use cases → adapters
- 前端使用 shadcn/ui + Tailwind，白色科技风
- Factory 模式创建 router（现有约定）
- `score` 领域字段不进 router（字段收缩原则）
- 所有 API 响应使用 `{"code": 0, "data": {...}}` 包装
- 中文代码注释、docstring

archived-with: 2026-07-04-kb-retrieve-pages
---

## 文件结构

```
# 后端新增/修改
alembic/versions/0002_add_tenant_id.py          [NEW] Migration
src/ragnexus/domain/models.py                   [MOD] +KnowledgeBase.tenant_id +RetrieveResult +TenantKBTree等
src/ragnexus/domain/ports.py                    [MOD] +KnowledgeBasePort create tenant_id +list_with_documents
src/ragnexus/domain/retrieval/fusion.py         [MOD] rrf_fuse 改造
src/ragnexus/application/create_kb_use_case.py  [MOD] +tenant_id
src/ragnexus/application/retrieve_use_case.py   [MOD] 签名扩展+RetrieveResult+分数标记+计时重构
src/ragnexus/application/kb_tree_use_case.py    [NEW] GetKnowledgeBaseTreeUseCase
src/ragnexus/adapters/knowledge_base/pg.py      [MOD] +create tenant_id +list_with_documents
src/ragnexus/adapters/rerank/llm.py             [MOD] +model_name +_rerank_score 写入
src/ragnexus/adapters/rerank/noop.py            [MOD] +model_name
src/ragnexus/adapters/http/create_kb_router.py  [MOD] +tenant_id
src/ragnexus/adapters/http/retrieve_router.py   [MOD] 完整请求/响应 schema
src/ragnexus/adapters/http/kb_tree_router.py    [NEW] GET /v1/knowledge-bases/tree
src/ragnexus/composition.py                     [MOD] 注册新 router+use case
demo_retrieve.py                                [MOD] 适配新签名

# 后端测试
tests/unit/test_rrf_fuse.py                     [MOD] 适配+新增分数合并用例
tests/unit/application/test_retrieve.py         [MOD] RetrieveResult
tests/unit/application/test_retrieve_hybrid.py  [MOD] 新签名
tests/unit/adapters/test_http_schema_invariance.py [MOD] 新schema
tests/integration/test_retrieve_full_chain.py   [MOD] meta 验证

# 前端新增/修改
admin/src/components/AppHeader.tsx              [NEW] 公共顶栏
admin/src/App.tsx                               [MOD] 路由重组
admin/src/pages/layout.tsx                      [MOD] 侧栏→AppHeader+Outlet
admin/src/pages/upload-doc.tsx                  [MOD] 合并创建KB表单
admin/src/pages/create-kb.tsx                   [DELETE]
admin/src/pages/knowledge-file-tree.tsx         [NEW] 列表页
admin/src/pages/retrieve.tsx                    [NEW] 检索调试页
admin/src/services/api.ts                       [MOD] 新接口
admin/src/types/api.ts                          [MOD] 新类型
admin/src/utils/storage.ts                      [MOD] 去掉localStorage

# 前端测试
admin/src/pages/upload-doc.test.tsx             [MOD] 适配
admin/src/pages/knowledge-file-tree.test.tsx    [NEW]
admin/src/pages/retrieve.test.tsx               [NEW]
```

archived-with: 2026-07-04-kb-retrieve-pages
---

### Task 1: Database Migration

**依赖:** 无
**文件:** 1 新文件

- [x] 1.1 创建 `alembic/versions/0002_add_tenant_id.py`
  - `ALTER TABLE knowledge_bases ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'`
  - 动态查询当前 constraint name：`SELECT conname FROM pg_constraint WHERE conrelid='knowledge_bases'::regclass AND contype='u'`
  - `DROP CONSTRAINT <cn>` + `ADD UNIQUE (tenant_id, name_key)`
  - **验证:** `alembic upgrade head && alembic downgrade -1`

### Task 2: Domain — models.py 扩展 + rrf_fuse 改造

**依赖:** 无
**文件:** 3 修改

- [x] 2.1 `models.py`: `KnowledgeBase` dataclass 加 `tenant_id: str = ""` 字段
- [x] 2.2 `models.py`: 新增 `RetrieveResult` dataclass
- [x] 2.3 `models.py`: 新增 Tree API 响应类型 `TenantKBTree`、`KBNode`、`DocNode`
- [x] 2.4 `fusion.py`: rrf_fuse 改造 — 预建 `kw_meta_map: dict[str, dict]`，合并两路 `_vector_score`/`_bm25_score`，新增 `_merge_metadata()` helper
- **验证:** `pytest tests/unit/test_rrf_fuse.py -v`（19 现有适配 + 新增 3-4 分数合并用例）

### Task 3: Create KB 链路 — tenant_id 支持

**依赖:** Task 1, Task 2
**文件:** 4 修改

- [x] 3.1 `ports.py`: `KnowledgeBasePort.create()` 签名加 `tenant_id: str`
- [x] 3.2 `knowledge_base/pg.py`: `create()` SQL 加 `tenant_id` 列，`RETURNING` 加 `tenant_id`
- [x] 3.3 `create_kb_use_case.py`: `execute()` 接受 `tenant_id`，校验 1–64 字符
- [x] 3.4 `create_kb_router.py`: `_CreateKBRequest` 加 `tenant_id: str = Field(...)`，响应加 `tenant_id`
- **验证:** `pytest tests/unit/application/ -k "create_kb" tests/unit/adapters/test_http_schema_invariance.py -v`

### Task 4: RetrieveUseCase 改造

**依赖:** Task 2
**文件:** 1 修改 + 2 修改

- [x] 4.1 `rerank/llm.py`: 新增 `model_name` 属性返回 `self.llm.model`；`_merge_and_sort` 返回前写 `metadata["_rerank_score"]`
- [x] 4.2 `rerank/noop.py`: 新增 `model_name` 属性返回 `None`
- [x] 4.3 `retrieve_use_case.py`:
  - 向量/BM25 召回后标记 `_vector_score`/`_bm25_score` 到各自 hit.metadata
  - `execute()` 签名扩展 (mode/vector_top_k/bm25_top_k/rrf_k/rerank_enabled/rerank_top_n)
  - 重构计时: `latency_ms` 计算从 finally → return 前，与 `RetrieveResult` 构造放一起
  - 返回值改为 `RetrieveResult`
  - 退化: ES 不可用 (`keyword_store=None` 且 mode=hybrid)→`degraded=True`；rerank 禁用→跳过调用
- **验证:** `pytest tests/unit/application/test_retrieve.py tests/unit/application/test_retrieve_hybrid.py -v`

### Task 5: Retrieve Router 升级

**依赖:** Task 4
**文件:** 1 修改

- [x] 5.1 `retrieve_router.py`:
  - `_RerankOptions` 嵌套模型
  - `_RetrieveRequest` 扩展 (mode/vector_top_k/bm25_top_k/rrf_k/rerank)
  - `_serialize_hit()` 用 `.get()` 非 `.pop()`，保持 metadata 完整；`filename` 映射到 `title`
  - 响应 meta 块：`total`, `latency_ms`, `mode`, `vector_count`, `bm25_count`, `fused_count`, `rerank_model`, `degraded`, `degraded_reason`
- **验证:** `pytest tests/unit/adapters/test_http_schema_invariance.py -v`

### Task 6: Tree API

**依赖:** Task 1, Task 3
**文件:** 3 新 + 1 修改

- [x] 6.1 `ports.py`: `KnowledgeBasePort` 加 `list_with_documents(keyword: str | None) -> list[TenantKBTree]`
- [x] 6.2 `knowledge_base/pg.py`: 实现 JOIN `knowledge_bases` + `documents`，按 tenant_id 分组，按 created_at/uploaded_at 倒序
- [x] 6.3 `kb_tree_use_case.py`: 新建 `GetKnowledgeBaseTreeUseCase`
- [x] 6.4 `kb_tree_router.py`: 新建 `GET /v1/knowledge-bases/tree`，factory 模式，`keyword` query 参数
- [x] 6.5 `composition.py`: 注册 new router + use case
- **验证:** `curl -s localhost:8000/v1/knowledge-bases/tree | python -m json.tool`

### Task 7: 前端 — AppHeader + 路由重组

**依赖:** 无 (纯前端，mock API)
**文件:** 3 新/改 + 1 删

- [x] 7.0 `npx shadcn add table`（列表页和检索结果页依赖）
- [x] 7.1 新建 `AppHeader.tsx` (52px, sticky, 左侧品牌名 "RAGNexus 调试控制台", 白色科技风)
- [x] 7.2 改 `layout.tsx`: 删 `<aside>` 侧栏，改为 `<AppHeader/>` + `<Outlet/>`
- [x] 7.3 改 `App.tsx`: 路由 `/`→UploadDocPage, `/knowledge-bases`→KnowledgeFileTreePage, `/retrieve`→RetrievePage
- [x] 7.4 删除 `create-kb.tsx`（功能已合并到 UploadDocPage）
- **验证:** `cd admin && npx vitest run`

### Task 8: 前端 — 首页合并

**依赖:** Task 6 (tree API 用于下拉) + Task 7 (路由)
**文件:** 1 修改 + 1 修改

- [x] 8.1 `upload-doc.tsx`: 顶部新增「创建知识库」Card (tenant_id + name + 创建按钮)
- [x] 8.2 `types/api.ts`: 加 `CreateKBRequest.tenant_id`, `CreateKBResponse.tenant_id`
- [x] 8.3 `services/api.ts`: `createKB()` 加 `tenant_id` 参数
- [x] 8.4 创建成功后刷新 KB 下拉（从 tree API 拉取）
- [x] 8.5 `storage.ts`: 移除 localStorage 读写逻辑
- **验证:** `cd admin && npx vitest run src/pages/upload-doc.test.tsx`

### Task 9: 前端 — 知识库列表页

**依赖:** Task 6 (Tree API) + Task 7 (路由)
**文件:** 1 新 + 2 修改

- [x] 9.1 `types/api.ts`: 加 `TreeItem`, `KBItem`, `DocItem` 类型
- [x] 9.2 `services/api.ts`: 加 `fetchTree(keyword?: string)` 函数
- [x] 9.3 `knowledge-file-tree.tsx`: 三级可展开树（租户→KB→文档）、搜索过滤 tenant_id、KB 行操作按钮（复制 ID / 跳转上传 / 跳转检索）、空状态
- **验证:** `cd admin && npx vitest run src/pages/knowledge-file-tree.test.tsx`

### Task 10: 前端 — 检索调试页

**依赖:** Task 5 (retrieve API) + Task 7 (路由) + Task 9 (共享类型)
**文件:** 1 新 + 2 修改

- [x] 10.1 `types/api.ts`: 加 `RetrieveRequest`, `RetrieveResponse`, `RetrieveHit`, `RetrieveMeta` 类型
- [x] 10.2 `services/api.ts`: 加 `retrieve(params: RetrieveRequest)` 函数
- [x] 10.3 `retrieve.tsx`:
  - 三 Card 布局（检索配置 / 检索与召回 / 运行摘要）
  - 检索配置: 租户/KB 选择（从 tree API 拉取选项）、top_k、mode tabs、hybrid 参数条件显示、rerank toggle
  - URL query params 预填 `tenant_id` + `kb_id`
  - 检索执行 + per-hit 分数 chips (score/vector/bm25/rerank) + 内容可折叠
  - 运行摘要网格 (latency_ms/mode/counts/degraded/rerank_model)
  - 表单校验 + 加载态 + 错误态 (toast + retry)
- **验证:** `cd admin && npx vitest run src/pages/retrieve.test.tsx`

### Task 11: 联调 & 验收

**依赖:** Task 1-10 全部
**文件:** 0 新

- [x] 11.1 `pytest` 全量后端测试通过
- [x] 11.2 `cd admin && npx vitest run` 全量前端测试通过
- [x] 11.3 E2E: 14 条全链路验收 (docs/acceptance-criteria.md 第四节)
- [x] 11.4 错误路径验证: API 5xx 前端 toast+retry, tree API 空数据→空状态, network error→降级提示

## 分组依赖图

```
Task 1 (migration)
  ↓
Task 2 (models + rrf_fuse) ← 无依赖，先跑
  ↓
Task 3 (create KB tenant_id) ←──→ Task 4 (RetrieveUseCase) [并行]
  ↓                                     ↓
Task 6 (tree API)                    Task 5 (retrieve router)
       ↓ (后端全部就绪)                   ↓
       └──────────── Task 7 (AppHeader) ──┘  [前端骨架，mock API]
                           ↓
                 ┌────────┼────────┐
                 ↓        ↓        ↓     [三路并行]
             Task 8    Task 9    Task 10
            (首页)    (列表)    (检索)
                 ↓        ↓        ↓
                 └────────┼────────┘
                          ↓
                    Task 11 (联调验收)
```

- Task 8 依赖: Task 6 (tree API 用于 KB 下拉) + Task 7 (路由)
- Task 9 依赖: Task 6 (tree API) + Task 7 (路由)
- Task 10 依赖: Task 5 (retrieve API) + Task 7 (路由) + Task 9 (共享 types/services)

## 关键风险

| 风险 | 缓解 |
|---|---|
| Task 2 改 models.py + rrf_fuse 后 19 个现有测试需适配 | Task 2 先行验证，逐个适配 |
| finally 块 latency 重构引入时序 bug | Task 4 显式单测覆盖计时 |
| name_key 联合唯一 migration 回滚复杂 | Task 1 双向验证 upgrade+downgrade |
| shadcn/ui Table 组件未安装导致 TS 报错 | Task 7.0 前置安装 |
| demo_retrieve.py 遗漏未更新 | Task 4 完成后一并更新（或 Task 3 验证中包含） |
