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
