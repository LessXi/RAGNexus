# Task 9: 前端 — 知识库列表页

## 依赖
- Task 6 (Tree API 端点)
- Task 7 (AppHeader + 路由重组)
- Task 8 (`fetchTree()` + TreeItem/KBItem/DocItem 类型已由 Task 8 在 api.ts 中定义，直接复用)

## 目标
新建 KnowledgeFileTreePage——调用 tree API，渲染三级可展开树（租户→KB→文档）。

## 文件
- **NEW**: `admin/src/pages/knowledge-file-tree.tsx`
- **复用**: `admin/src/types/api.ts` — TreeItem/KBItem/DocItem 类型由 Task 8 定义
- **复用**: `admin/src/services/api.ts` — fetchTree() 由 Task 8 实现

## 具体需求

### 9.1 类型和服务（已由 Task 8 提供）
**不修改** `types/api.ts` 和 `services/api.ts`。Task 8 已经定义好了：
- `TreeItem`, `KBItem`, `DocItem` 类型
- `fetchTree(keyword?: string)` 函数

直接 import 使用即可。

### 9.2 knowledge-file-tree.tsx

- 三级可展开树结构：
  - L1: 租户名（tenant_id）— 可折叠
  - L2: KB 名（name + kb_id badge）— 可折叠
  - L3: 文档名（filename + status 标签）
- 顶部搜索框：按 tenant_id 模糊过滤（调 fetchTree(keyword)）
- KB 行操作按钮：
  - 📋 复制 kb_id（toast 提示「已复制」）
  - ⬆️ 跳转上传页（`/?kb_id=xxx`）
  - 🔍 跳转检索页（`/retrieve?tenant_id=xxx&kb_id=yyy`）
- 空状态：「暂无知识库，去上传页创建」
- 加载态：Skeleton / Spinner
- 使用 shadcn/ui Table 组件

## 验证
```bash
cd admin && npx vitest run src/pages/knowledge-file-tree.test.tsx
```

## 全局约束
- React 18 + TypeScript + Tailwind CSS + shadcn/ui
- 白色科技风
- 中文注释
- shadcn/ui Table 组件（已在 Task 7.0 安装）
