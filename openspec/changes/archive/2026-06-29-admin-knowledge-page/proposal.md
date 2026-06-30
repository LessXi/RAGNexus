## Why

RAGNexus 目前缺少可视化的知识库管理界面，所有操作依赖 API 调用或命令行脚本。对于调优测试场景，需要一个轻量级管理后台来快速创建知识库、上传文档，并直观看到上传结果。这是产品化的第一步，后续可逐步添加鉴权、知识库列表管理等能力。

## What Changes

- 在项目根目录新建 `admin/` 独立前端项目（Vite + React 18 + TypeScript）
- 添加「知识库创建」页面：输入名称创建 KB，展示创建结果
- 添加「文档上传」页面：选择 KB + 选择文件/文件夹，顺序上传并展示成功/失败结果
- 前端本地缓存已创建的知识库列表（因后端暂无 list 端点，不做后端改动）

## Capabilities

### New Capabilities

- `admin-knowledge-page`: 独立前端管理后台，提供知识库创建和文档上传的 Web UI

### Modified Capabilities

无（不修改任何后端代码）

## Impact

- **代码**: 全部新增，`admin/` 目录独立于现有 `src/ragnexus/`
- **新增文件**: `admin/` 下全套 Vite + React + TypeScript 项目
- **依赖**: 前端依赖（react, vite, tailwindcss, shadcn/ui 等），不涉及后端依赖变更
- **数据库**: 无变更
- **API**: 不修改任何后端 API，仅消费现有 `POST /v1/knowledge-bases:create` 和 `POST /v1/documents:upload`
