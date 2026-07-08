# Task 10: 前端 — 检索调试页

## 依赖
- Task 5 (retrieve API 就绪)
- Task 7 (AppHeader + 路由重组)
- Task 9 (KnowledgeFileTreePage 已就绪，共享 types/services)

## 目标
新建 RetrievePage — 完整的检索调试界面，三 Card 布局。

## 文件
- **NEW**: `admin/src/pages/retrieve.tsx`
- **MOD**: `admin/src/types/api.ts` — 加 RetrieveRequest/Response/Hit/Meta 类型（如 Task 9 未加）
- **MOD**: `admin/src/services/api.ts` — 加 retrieve() 函数

## 具体需求

### 10.1 types/api.ts
```typescript
export interface RetrieveRequest {
  query: string;
  kb_ids: string[];
  top_k?: number;
  mode?: "vector" | "bm25" | "hybrid";
  vector_top_k?: number;
  bm25_top_k?: number;
  rrf_k?: number;
  rerank?: {
    enabled: boolean;
    top_n?: number;
  };
}

export interface RetrieveHit {
  chunk_id: string;
  kb_id: string;
  doc_id: string;
  score: number;
  text: string;
  title: string;
  metadata: Record<string, unknown>;
  vector_score?: number;
  bm25_score?: number;
  rerank_score?: number;
}

export interface RetrieveMeta {
  total: number;
  latency_ms: number;
  mode: string;
  vector_count: number;
  bm25_count: number;
  fused_count: number;
  rerank_model: string | null;
  degraded: boolean;
  degraded_reason: string | null;
}

export interface RetrieveResponse {
  code: number;
  data: {
    hits: RetrieveHit[];
    meta: RetrieveMeta;
  };
}
```

### 10.2 services/api.ts
```typescript
export async function retrieve(params: RetrieveRequest): Promise<RetrieveResponse> {
  const res = await fetch("/v1/rag:retrieve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  return res.json();
}
```

### 10.3 retrieve.tsx — 页面布局
三 Card 布局（使用 shadcn/ui Card）：

**Card 1: 检索配置**（可折叠，默认展开）
- 租户选择（下拉，从 tree API 拉取选项，可选）
- KB 选择（下拉，从 tree API 拉取选项，必填，过滤选中租户的 KB）
- top_k（number input，1-50，默认 5）
- mode tabs（vector | bm25 | hybrid）
- hybrid 参数条件显示（仅 mode=hybrid 时）：
  - vector_top_k (1-200, default 20)
  - bm25_top_k (1-200, default 20)
  - rrf_k (1-200, default 60)
- rerank toggle + top_n (1-20, default 5)

**Card 2: 检索结果**
- query 输入框 + 检索按钮
- 结果列表：每条显示
  - title + 分数 chips（score | vector | bm25 | rerank — 有值才显示，null 隐藏）
  - 内容 text（可折叠，默认折叠前 120 字符）
  - chunk_id / doc_id 小字显示

**Card 3: 运行摘要**
- Grid 布局展示 meta 字段：total, latency_ms, mode, vector_count, bm25_count, fused_count, rerank_model
- degraded 警告（红色提示，显示 degraded_reason）

### 10.4 URL query params 预填
从列表页跳转时 URL 带 `?tenant_id=xxx&kb_id=yyy`，自动预填表单。

### 10.5 表单校验 + 状态
- query 必填（非空）
- kb_ids 至少选一个（否则检索按钮 disabled）
- 加载态：检索按钮 loading spinner
- 错误态：toast (`sonner` 或 shadcn toast) + retry 按钮

## 验证
```bash
cd admin && npx vitest run src/pages/retrieve.test.tsx
```

## 全局约束
- React 18 + TypeScript + Tailwind CSS + shadcn/ui
- 白色科技风
- 中文注释
- shadcn/ui Card, Input, Button, Select, Tabs, Switch 组件
