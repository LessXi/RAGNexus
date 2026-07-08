# Task 8: 前端 — 首页合并（创建 KB + 上传）

## 依赖
- Task 6 (Tree API 用于 KB 下拉刷新)
- Task 7 (AppHeader + 路由重组)

## 目标
在 UploadDocPage 顶部新增「创建知识库」Card，移除 localStorage 依赖。

## 文件
- **MOD**: `admin/src/pages/upload-doc.tsx` — 新增创建 KB Card
- **MOD**: `admin/src/types/api.ts` — 加 CreateKBRequest.tenant_id, CreateKBResponse.tenant_id
- **MOD**: `admin/src/services/api.ts` — createKB() 加 tenant_id 参数
- **MOD**: `admin/src/utils/storage.ts` — 移除 localStorage 读写逻辑

## 具体需求

### 8.1 UploadDocPage 顶部新增创建 KB Card
- 可折叠 Card（默认展开）
- 两个输入框：tenant_id（必填，1-64 字符）+ name（必填）
- 创建按钮（调用 createKB API）
- 创建成功后：toast 提示 + 清空表单 + 刷新 KB 下拉

### 8.2 types/api.ts
```typescript
export interface CreateKBRequest {
  name: string;
  tenant_id: string;
}

export interface CreateKBResponse {
  id: string;
  name: string;
  tenant_id: string;
  name_key: string;
  created_at: string;
}
```

### 8.3 services/api.ts
- `createKB()` 接受 `{ name, tenant_id }` 对象
- 返回类型 `CreateKBResponse`

### 8.4 KB 下拉数据源迁移
- 当前从 localStorage 读取 → 改为从 tree API (`fetchTree()`) 拉取
- 创建 KB 成功后重新调 `fetchTree()` 刷新选项

### 8.5 storage.ts
- 移除所有 `localStorage.getItem/setItem` 逻辑
- 如果整个文件只剩空导出，可以删除

## 验证
```bash
cd admin && npx vitest run src/pages/upload-doc.test.tsx
```

## 全局约束
- React 18 + TypeScript + Tailwind CSS + shadcn/ui
- 白色科技风
- 中文注释
- 保持与现有组件一致的代码风格
- `fetchTree()` 函数在 Task 9 中由另一个 agent 创建，本 task 可直接在 api.ts 中定义或跳过（先用 mock，后续 Task 9 会补上真实实现）
