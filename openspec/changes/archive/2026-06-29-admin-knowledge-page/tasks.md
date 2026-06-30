## 1. 项目脚手架

- [ ] 1.1 用 Vite 创建 React + TypeScript 项目（`admin/` 目录）
- [ ] 1.2 安装依赖：tailwindcss, shadcn/ui, react-router-dom, @tanstack/react-query, axios, react-hook-form, zod
- [ ] 1.3 配置 Tailwind CSS + PostCSS
- [ ] 1.4 初始化 shadcn/ui（components.json + 基础组件）
- [ ] 1.5 配置 Vite 代理（开发环境 `/v1` → `http://localhost:8000`）

## 2. 基础设施

- [ ] 2.1 创建 `lib/axios.ts`（axios 实例，baseURL='' + timeout=300000）
- [ ] 2.2 创建 `types/api.ts`（CreateKBRequest/Response, UploadDocResponse, ApiError 等类型）
- [ ] 2.3 创建 `services/api.ts`（createKB + uploadDoc 函数，含响应拦截器错误码映射）
- [ ] 2.4 创建 `utils/storage.ts`（localStorage 缓存已创建 KB 列表，含 try/catch 防损坏）
- [ ] 2.5 创建 `utils/file-filter.ts`（preFilterFiles: 扩展名/大小/空文件客户端预过滤）
- [ ] 2.6 创建 `components/provider/query-provider.tsx`（React Query Provider）
- [ ] 2.7 创建 `index.css`（Tailwind 指令 + 基础样式）

## 3. 布局与路由

- [ ] 3.1 创建 `App.tsx`（BrowserRouter + QueryProvider + 路由配置）
- [ ] 3.2 创建 `pages/layout.tsx`（侧栏导航: 知识库管理 | 文档上传）
- [ ] 3.3 添加 shadcn/ui 组件：Button, Input, Label, Card, Table, Badge, Toaster, Progress
- [ ] 3.4 实现 webkitdirectory 特征检测降级（不支持时隐藏文件夹按钮 + 提示）
## 4. 知识库创建页

- [ ] 4.1 创建 `hooks/use-create-kb.ts`（React Query mutation）
- [ ] 4.2 创建 `pages/create-kb.tsx`：
  - 表单：名称输入 + 提交（React Hook Form + Zod 校验 1-64 字符）
  - 结果区：创建成功后展示 kb_id（可复制）+ name + created_at
  - 错误处理：名称已存在 / 网络错误
  - 已创建列表：从 localStorage 读取，支持点击跳转上传页

## 5. 文档上传页

- [ ] 5.1 创建 `utils/upload-queue.ts`（顺序上传队列：async/await 遍历 + per-file 错误隔离 + 进度回调）
- [ ] 5.2 创建 `pages/upload-doc.tsx`：
  - KB 选择：下拉列表（localStorage）+ 手动输入 kb_id
  - 文件选择：单个/多个文件 + 文件夹（webkitdirectory）→ 调 preFilterFiles 预过滤
  - 已选文件预览列表（文件名 + 大小；被跳过文件灰色展示 + 跳过原因）
  - 上传逻辑：调 uploadQueue 顺序执行
  - 进度提示：当前正在上传的文件名 + 进度 X/N + 成功/失败实时计数
  - beforeunload 保护：上传进行中时拦截页面关闭
  - 结果表格：文件名 | 大小 | 状态(✅/❌) | 详情(成功chunk数/失败原因)
  - 汇总：合计/成功/失败计数；[继续上传] [清空重来] 按钮

## 6. 联调验证

- [ ] 6.1 启动后端 + 前端，验证创建 KB 全流程
- [ ] 6.2 验证单文件上传（.md / .txt）+ 结果显示
- [ ] 6.3 验证文件夹上传（多文件混合）+ 顺序进度
- [ ] 6.4 验证错误场景：重名 KB / 重名文件(10302) / 不支持格式 / 超大文件 / 无效 kb_id(10300) / 空文件 / 无扩展名
- [ ] 6.5 验证 localStorage 缓存在 KB 创建后的正确性
- [ ] 6.6 验证客户端预过滤：0字节/超10MB/不支持格式的跳过展示
- [ ] 6.7 验证网络断开场景：上传中断后各文件状态正确
- [ ] 6.8 验证浏览器降级：Firefox 隐藏文件夹按钮
- [ ] 6.9 验证 beforeunload 拦截：上传中点关闭页面弹出确认
