# Task 7: 前端 — AppHeader + 路由重组

## 依赖
- 无（纯前端，可 mock API）

## 目标
1. 安装 shadcn/ui Table 组件
2. 新建公共 AppHeader 组件（白色科技风）
3. 重写 Layout：AppHeader + Outlet，去掉侧栏
4. 重组 App.tsx 路由表
5. 删除旧的 create-kb.tsx

## 文件
- **RUN**: `npx shadcn add table`（前置依赖安装）
- **NEW**: `admin/src/components/AppHeader.tsx`
- **MOD**: `admin/src/App.tsx`
- **MOD**: `admin/src/pages/layout.tsx`
- **DELETE**: `admin/src/pages/create-kb.tsx`

## 具体需求

### 5.0 前置安装
```bash
cd admin && npx shadcn add table
```

### 5.1 AppHeader 组件
- 高度 52px，sticky top-0，z-50
- 白色背景 + 底部细边框 (border-b border-gray-200)
- 左侧: 品牌名 "RAGNexus 调试控制台"（text-lg font-semibold text-gray-800）
- 无导航链接（后端管理台，不需要多级导航）
- 白色科技风：干净、留白充足、无彩色、圆角适度

### 5.2 Layout 重写
- 当前 layout.tsx 有 `<aside>` 侧栏 → 全部删除
- 改为: `<AppHeader />` + `<main className="container mx-auto px-4 py-6"><Outlet /></main>`
- 保持 React Router `<Outlet />` 模式

### 5.3 App.tsx 路由重组
```tsx
<Route path="/" element={<UploadDocPage />} />
<Route path="/knowledge-bases" element={<KnowledgeFileTreePage />} />
<Route path="/retrieve" element={<RetrievePage />} />
```
- KnowledgeFileTreePage 和 RetrievePage 暂时用 placeholder 组件（后续 Task 9/10 替换）
- UploadDocPage 是现有的首页

### 5.4 删除 create-kb.tsx
- 删除文件 `admin/src/pages/create-kb.tsx`
- 从 App.tsx 移除相关 import 和路由
- 功能已合并到 UploadDocPage（Task 8）

## 验证
```bash
cd admin && npx vitest run
```
确保现有测试通过（UploadDocPage 相关测试），新组件不引入 TS 编译错误。

## 全局约束
- React 18 + TypeScript + Tailwind CSS + shadcn/ui
- 白色科技风设计（参考项目现有 UI 风格）
- 中文注释
- 保持与现有组件一致的代码风格
