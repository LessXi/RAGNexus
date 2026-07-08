## 1. Database Migration

- [x] 1.1 创建 Alembic migration `0002_add_tenant_id.py`：`knowledge_bases` 新增 `tenant_id TEXT NOT NULL DEFAULT 'default'`，`name_key` 唯一约束改为 `(tenant_id, name_key)` 联合唯一
- [x] 1.2 更新 `PgKnowledgeBaseRepository.create()` 接受并写入 `tenant_id`，冲突检测改为联合唯一
- [x] 1.3 更新 `KnowledgeBasePort.create()` 协议签名（加 `tenant_id` 参数）
- [x] 1.4 更新 `CreateKnowledgeBaseUseCase.execute()` 接受 `tenant_id`，校验 1–64 字符
- [x] 1.5 更新 `create_kb_router.py`：请求体加 `tenant_id`，响应加 `tenant_id`
- [x] 1.6 更新 `demo_retrieve.py` 和受影响的测试（create KB 调用加 `tenant_id`）

## 2. Retrieve 链路改造（per-chunk 分数 + RetrieveResult）

- [x] 2.1 `models.py` 新增 `RetrieveResult` dataclass（hits + meta 字段，含 `degraded_reason`）
- [x] 2.2 `retrieve_use_case.py`：向量和 BM25 召回后，立即标记 `_vector_score` / `_bm25_score` 到各自 hit.metadata
- [x] 2.3 `fusion.py` 改造 `rrf_fuse`：合并两路 `_vector_score` / `_bm25_score`（在 2.2 标记完成后进行）
- [x] 2.4 `retrieve_use_case.py`：`execute()` 签名扩展——接受 `mode`、`candidate_k`（由 `vector_top_k`/`bm25_top_k` 映射）、`rrf_k`、`rerank_enabled`、`rerank_top_n`
- [x] 2.5 `retrieve_use_case.py`：重构计时——将 `latency_ms` 计算从 `finally` 块移到 `return` 之前，与 `RetrieveResult` 构造放一起
- [x] 2.6 `retrieve_use_case.py`：返回值改为 `RetrieveResult`，打包 hits + 运行元信息
- [x] 2.7 `rerank/llm.py`：新增 `model_name` 属性返回 `self.llm.model`；`_merge_and_sort` 返回前将 `chunk_scores` 写入 `metadata["_rerank_score"]`
- [x] 2.8 `rerank/noop.py`：`NoopRerankProvider` 新增 `model_name` 属性返回 `None`

## 3. Retrieve API（请求/响应 schema 升级）

- [x] 3.1 `retrieve_router.py`：`_RetrieveRequest` 扩展——`mode`、`vector_top_k`、`bm25_top_k`、`rrf_k`、`rerank` 嵌套对象
- [x] 3.2 `retrieve_router.py`：响应序列化——提取 `_` 前缀字段到 per-hit 顶层字段，构建 `meta` 块（含 `total`、`latency_ms`、`degraded_reason`）
- [x] 3.3 `retrieve_router.py`：router 内部适配 `RetrieveResult` 新返回类型（composition.py 装配不变，router factory 自包含）
## 4. Tree API（新增）

- [x] 4.1 `KnowledgeBasePort` 新增 `list_with_documents(keyword: str | None)` 方法签名
- [x] 4.2 `PgKnowledgeBaseRepository` 实现 `list_with_documents()`——JOIN knowledge_bases + documents，组装三级树
- [x] 4.3 新建 `GetKnowledgeBaseTreeUseCase`，委托 repo
- [x] 4.4 新建 `GET /v1/knowledge-bases/tree` router，含 `keyword` query 参数
- [x] 4.5 `composition.py` 注册新 router 和 use case

## 5. 前端：AppHeader + 路由重组

- [x] 5.0 安装 shadcn/ui Table 组件：`npx shadcn add table`（列表页和检索结果页依赖）
- [x] 5.1 新建 `AppHeader` 组件（白色科技风、52px、sticky、左侧品牌名，参考 ui-design-mockup.html）
- [x] 5.2 重写 `Layout` 为 `AppHeader + Outlet` 结构，去掉侧栏
- [x] 5.3 `App.tsx` 路由表：`/` → UploadDocPage、`/knowledge-bases` → KnowledgeFileTreePage、`/retrieve` → RetrievePage
- [x] 5.4 删除旧的 `create-kb.tsx` 页面文件（功能已合并到 UploadDocPage）

- [x] 6.1 `UploadDocPage` 顶部新增「创建知识库」Card（tenant_id + name + 按钮）
- [x] 6.2 创建 KB 后更新本地下拉选项（从 tree API 刷新）
- [x] 6.3 KB 下拉数据源从 localStorage → tree API 调用
- [x] 6.4 去掉 `storage.ts` 的 localStorage 逻辑

## 7. 前端：知识库列表页

- [x] 7.1 新建 `KnowledgeFileTreePage`——调用 tree API，渲染三级可展开树
- [x] 7.2 搜索框：按 tenant_id 模糊过滤
- [x] 7.3 KB 行操作按钮：复制 kb_id、跳转上传（带 kb_id）、跳转检索（带 query params）
- [x] 7.4 空状态和加载态

## 8. 前端：检索调试页

- [x] 8.1 新建 `RetrievePage`——检索配置（可折叠）+ 检索召回 + 运行摘要三 Card
- [x] 8.2 检索配置：租户/KB 选择、top_k、mode tabs、hybrid 参数（条件显示）、rerank toggle
- [x] 8.3 URL query params 预填（从列表页跳转带入 tenant_id + kb_id）
- [x] 8.4 检索执行 + 结果渲染（per-hit 分数 chips、文档内容可折叠）
- [x] 8.5 运行摘要 Card（meta 字段展示）
- [x] 8.6 表单校验 + 加载态 + 错误态
## 9. 联调 & 验收
- [x] 9.1 全量后端单元测试通过（含 rrf_fuse 新逻辑 + 分数合并用例）
- [x] 9.2 全量前端 unit test 通过
- [x] 9.3 E2E：14 条全链路验收（docs/acceptance-criteria.md 第四节）
- [x] 9.4 回归：首页上传逻辑不受影响
- [x] 9.5 错误路径：API 5xx 前端 toast + retry、tree API 空数据空状态、network error 降级提示
