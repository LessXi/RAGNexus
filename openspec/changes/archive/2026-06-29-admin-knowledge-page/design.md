# Admin Knowledge Page — 设计文档

## 1. 架构概述

```
admin/                          # 独立前端项目
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
├── components.json             # shadcn/ui 配置
├── src/
│   ├── main.tsx                # 入口
│   ├── App.tsx                 # 路由挂载
│   ├── index.css               # Tailwind 入口
│   ├── components/
│   │   ├── provider/
│   │   │   └── query-provider.tsx   # React Query Provider
│   │   └── ui/                      # shadcn/ui 自动生成的组件
│   ├── pages/
│   │   ├── layout.tsx               # 全局布局（侧栏导航）
│   │   ├── create-kb.tsx            # 创建知识库页
│   │   └── upload-doc.tsx           # 文档上传页
│   ├── services/
│   │   └── api.ts                   # axios 封装 + 所有 API 调用
│   ├── hooks/
│   │   ├── use-create-kb.ts         # 创建 KB mutation
│   │   └── use-upload-doc.ts        # 上传文档 mutation
│   ├── types/
│   │   └── api.ts                   # 请求/响应类型
│   ├── lib/
│   │   └── axios.ts                 # axios 实例
│   └── utils/
│       └── storage.ts               # localStorage 工具
```

## 2. 路由设计

| 路径 | 页面 | 说明 |
|------|------|------|
| `/` | Layout + 重定向 | 默认跳转到 `/knowledge-bases` |
| `/knowledge-bases` | CreateKB | 知识库管理（创建 + 列表） |
| `/upload` | UploadDoc | 文档上传 |

## 3. 组件树

```
<App>
  <QueryProvider>
    <BrowserRouter>
      <Layout>                    # 侧栏 + 内容区
        <Sidebar>                 # 导航: 知识库管理 | 文档上传
        <main>
          <Routes>
            <Route "/knowledge-bases" → <CreateKBPage />>
            <Route "/upload" → <UploadDocPage />>
          </Routes>
        </main>
      </Layout>
    </BrowserRouter>
  </QueryProvider>
</App>
```

## 4. 数据流

### 4.1 知识库创建

```
用户输入 name → React Hook Form + Zod 校验
  → useCreateKB mutation (POST /v1/knowledge-bases:create)
    → 成功: 展示 kb_id + name + created_at，写入 localStorage
    → 失败: 展示错误信息（如 "名称已存在"）
```

### 4.2 文档上传

```
用户选择 KB（从 localStorage 列表或手动输入 kb_id）
  → 选择文件/文件夹（input[type=file] webkitdirectory + multiple）
    → 构建上传队列: File[]
      → 顺序遍历队列，每个文件:
        → useUploadDoc mutation (POST /v1/documents:upload, multipart)
          → 成功: 记录到 results.success[]
          → 失败: 记录到 results.failed[]，带错误信息
      → 全部完成后展示汇总表格
```

### 4.3 localStorage 缓存策略

由于后端无 list KBs 端点，前端用 localStorage 缓存已创建的 KB：

```typescript
// storage.ts
interface CachedKB {
  kb_id: string;
  name: string;
  created_at: string;
}

function getKBs(): CachedKB[] { ... }
function addKB(kb: CachedKB): void { ... }
function removeKB(kb_id: string): void { ... }
```

- 只增不删（删除功能后续版本添加）
- 作为上传页 KB 选择器的数据源

## 5. API 层设计

### 5.1 axios 实例 (`lib/axios.ts`)

```typescript
const api = axios.create({
  baseURL: '',                      // 开发走 Vite proxy，生产由构建注入
  timeout: 300_000,                 // 大文件 embedding 可能需要数分钟
});
```

### 5.2 API 函数 (`services/api.ts`)

```typescript
// 创建知识库
async function createKB(name: string): Promise<CreateKBResponse>

// 上传文档
async function uploadDoc(kb_id: string, file: File): Promise<UploadDocResponse>
```

### 5.3 错误处理

统一拦截 axios error，解析后端返回的 `{code, message, data, errors?}` 结构：
- `code === 0` → 成功（上传接口 HTTP 201 也走此逻辑）
- `code === 10001` (PARAM_ERROR) → 参数校验失败（如 name 长度超限）
- `code === 10300` (NOT_FOUND) → KB 不存在（上传到无效 kb_id）
- `code === 10301` (RESOURCE_CONFLICT) → 名称已存在（创建 KB 重名）
- `code === 10302` (RESOURCE_EXISTS) → 文件重复（同一文件已上传）
- `code === 10400` (UNSUPPORTED_FORMAT) → 文件类型不支持
- `code === 10401` (FILE_TOO_LARGE) → 文件超过 10MB 上限
- `code === 10402` (FILE_EMPTY) → 文件内容为空
- `code === -1` (axios 网络错误) → 无法连接后端服务，检查服务是否启动
- 其他 → 通用错误，展示 `message` 字段

`errors` 数组（如有）包含 `[{field, reason}]` 可做字段级提示。

### 5.4 CORS 与代理策略

后端当前 **无 CORS 中间件**（composition.py 中未配置 CORSMiddleware）。按约束不修改后端代码，解决方案分层：

| 环境 | 方案 | 详情 |
|------|------|------|
| 开发 | Vite proxy | `vite.config.ts` 中配置 `/v1` → `http://localhost:8000`，浏览器看到同源，绕过 CORS |
| 生产 | 反向代理 | 用户部署时需配置 nginx/caddy 将 `/v1/*` 代理到后端，README 提供配置示例 |

axios `baseURL` 在开发环境为空字符串（走 Vite proxy），生产环境通过 `VITE_API_BASE` 环境变量注入：

```typescript
// 开发: 空字符串 → 所有请求走 Vite proxy
// 生产: VITE_API_BASE=https://api.example.com → 直连后端（需后端配 CORS 或用反向代理同域部署）
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '',
  timeout: 300_000,
});
```

### 5.5 客户端文件预过滤

在发起上传请求前，对用户选择的文件进行客户端预过滤，减少无效网络请求：

```typescript
interface FilterResult {
  valid: File[];
  skipped: { name: string; size: number; reason: string }[];
}

function preFilterFiles(files: FileList | File[]): FilterResult {
  const ALLOWED_EXTS = ['.md', '.txt'];
  const MAX_SIZE = 10 * 1024 * 1024; // 10MB
  const valid: File[] = [];
  const skipped: FilterResult['skipped'] = [];

  for (const file of files) {
    if (file.size === 0) {
      skipped.push({ name: file.name, size: 0, reason: '文件为空' });
      continue;
    }
    if (file.size > MAX_SIZE) {
      skipped.push({ name: file.name, size: file.size, reason: '超过 10MB 限制' });
      continue;
    }
    const ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
    if (!ALLOWED_EXTS.includes(ext)) {
      skipped.push({ name: file.name, size: file.size, reason: `不支持的类型 (${ext || '无扩展名'})` });
      continue;
    }
    valid.push(file);
  }
  return { valid, skipped };
}
```

预过滤结果在文件预览区展示：被跳过的文件显示灰色 + 跳过原因；有效文件正常显示。用户点击「开始上传」时只上传 `valid` 列表。


## 6. 上传结果展示

上传完成后展示汇总表格：

| 文件名 | 大小 | 状态 | 详情 |
|--------|------|------|------|
| doc1.md | 5KB | ✅ 成功 | doc_abc123, 3 chunks |
| doc2.txt | 2KB | ❌ 失败 | 文件类型不支持 |
| doc3.md | 8KB | ✅ 成功 | doc_def456, 5 chunks |

底部显示：合计 X 个文件，Y 成功，Z 失败。

## 7. UI 设计要点

### 7.1 CreateKB 页
- 顶部：页面标题 + 描述
- 表单区：名称输入框 + 提交按钮
- 结果区：创建成功后展示 kb_id（可复制）+ 名称 + 时间
- 列表区：已创建的知识库列表（来自 localStorage），可点击跳转到上传页并预选该 KB

### 7.2 UploadDoc 页
- KB 选择区：下拉列表（来自 localStorage）+ 手动输入 kb_id 的备选
- 文件选择区：
  - "选择文件" 按钮（单选/多选）
  - "选择文件夹" 按钮（webkitdirectory）
  - 已选文件预览列表（文件名 + 大小）
- 上传进度区：进度条 + 当前正在上传的文件名
- 结果表格：上传完成后展示

## 8. 技术细节

### 8.1 文件夹上传实现

HTML 文件夹选择通过 `<input type="file" webkitdirectory>` 实现。
获取 FileList 后提取所有 .md/.txt 文件，构建上传队列。
注意：文件夹中的嵌套子文件夹文件也会被浏览器递归列出。

### 8.2 上传并发控制

虽然是"一个一个顺序传输"，但实现用 async/await 循环，每个文件等待上一个完成后再上传下一个。
这样实现简单且后端无并发压力。

### 8.3 shadcn/ui 组件使用

需要使用的组件：
- `Button` — 提交/操作按钮
- `Input` — 文本输入
- `Label` — 表单标签
- `Card` — 内容卡片
- `Table` — 结果表格
- `Badge` — 状态标签（成功/失败）
- `Progress` — 上传进度条（可选）
- `Toaster` + `toast` — 操作反馈通知

### 8.4 Vite 代理配置（开发环境）

```typescript
// vite.config.ts
export default defineConfig({
  server: {
    proxy: {
      '/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
```

### 8.5 边界条件处理矩阵

#### 知识库创建

| # | 边界条件 | 检测层 | 处理策略 |
|---|---------|--------|---------|
| 1 | 名称空/纯空格 | Zod + trim | 前端拦截，"知识库名称不能为空" |
| 2 | 名称 > 64 字符 | Zod + HTML maxLength | 前端拦截 |
| 3 | 快速双击提交 | React Query isPending | 按钮 disabled，防重复提交 |
| 4 | 后端不在线 | axios catch NetworkError | "无法连接后端服务 (localhost:8000)，请确认服务已启动" |
| 5 | 请求超时 | axios timeout (10s) | "请求超时，请检查后端状态" |
| 6 | 5xx 服务器错误 | axios response interceptor | 展示 `code + message` |
| 7 | 响应 JSON 结构异常 | 防御性解析 | try/catch → "服务器响应格式异常" |
| 8 | localStorage 配额满 | try/catch setItem | toast "本地缓存失败，但知识库已创建成功，请手动记录 kb_id" |
| 9 | localStorage 数据损坏 | try/catch JSON.parse | 静默清除损坏数据，重新初始化为空数组 |

#### 文档上传

| # | 边界条件 | 检测层 | 处理策略 |
|---|---------|--------|---------|
| 1 | 未选 KB | UI 状态 | 按钮 disabled，占位文字提示 |
| 2 | 未选文件 | UI 状态 | 按钮 disabled |
| 3 | 0 字节文件 | 客户端预过滤 | 跳过，标记 "文件为空" |
| 4 | >10MB 文件 | 客户端预过滤 | 跳过，标记 "超过 10MB 限制" |
| 5 | .pdf/.docx 等 | 客户端预过滤 | 跳过，标记 "不支持的类型 (.xxx)" |
| 6 | 无扩展名文件 | 客户端预过滤 | 跳过，标记 "不支持的类型 (无扩展名)" |
| 7 | 同文件上传两次 | 后端 10302 | 第二个标记 "文件已存在"（SHA256 去重） |
| 8 | 文件夹 100+ 文件 | 客户端计数 | >50 时弹出提示 "文件较多（N个），上传可能需要几分钟" |
| 9 | 嵌套子目录文件 | webkitdirectory 递归 | 文件名展示完整相对路径（如 `subdir/readme.md`） |
| 10 | 某文件上传失败 | per-file error catch | **不阻断后续文件**，记录到失败列表 |
| 11 | 中途网络断开 | axios catch | 当前文件失败 → 后续文件逐个失败 → 汇总展示全部失败 |
| 12 | 上传中关闭标签页 | beforeunload 事件 | `e.preventDefault()` → 浏览器弹窗 "上传进行中，确定离开？" |
| 13 | 大文件超时 | axios timeout (300s) | 单个文件标记 "上传超时"，继续下一个 |
| 14 | 后端返回 HTML | JSON 解析失败 | "服务器响应异常" |
| 15 | 后端返回 code=10300 | response interceptor | "知识库不存在，请确认 kb_id 正确" |
| 16 | 文件夹含不支持格式 | 预过滤 | 跳过的文件在预过滤阶段统计，展示 "已跳过 N 个不支持的文件" |

### 8.6 浏览器兼容性降级

| 特性 | Chrome | Edge | Firefox | Safari |
|------|--------|------|---------|-------|
| `webkitdirectory`（文件夹选择） | ✅ | ✅ | ✅ | ❌ |
| `input[multiple]`（多文件选择） | ✅ | ✅ | ✅ | ✅ |
| `navigator.clipboard.writeText`（复制 kb_id） | ✅ | ✅ | ✅ | ✅ |

**降级策略**：页面加载时检测 `'webkitdirectory' in HTMLInputElement.prototype`：
- 支持 → 显示「选择文件夹」按钮
- 不支持 → 隐藏按钮，显示提示 "当前浏览器不支持文件夹选择，请使用 Chrome 或 Edge"

**最低兼容目标**：Chrome 90+, Edge 90+, Firefox 100+, Safari 15+。


## 9. 不做的事（明确范围边界）

- ❌ 不做鉴权（后续版本添加）
- ❌ 不做知识库删除
- ❌ 不做文档删除/管理
- ❌ 不做检索测试界面
- ❌ 不修改任何后端代码
- ❌ 不做拖拽上传（本期用原生文件选择器）
- ❌ 不做实时进度推送（用简单的文件级顺序状态）
- ❌ 不做暗色模式切换

## 10. 测试策略

- 本 change 不做自动化测试（纯前端 UI，且与已有 Python 测试体系不兼容）
- 手动验证清单：
  1. 创建 KB → 验证返回 kb_id 并缓存到 localStorage
  2. 重复创建同名 KB → 验证错误提示
  3. 上传单个 .md 文件 → 验证成功 + chunk_count
  4. 上传单个 .txt 文件 → 验证成功
  5. 上传不支持的格式（如 .pdf）→ 验证后端拒绝
  6. 文件夹上传（含多个 .md/.txt）→ 验证逐个上传 + 结果汇总
  7. 上传到不存在的 kb_id → 验证后端错误提示
  8. 上传超大文件（>10MB）→ 验证后端拒绝
