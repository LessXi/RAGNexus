# Phase 5 前端适配 — 实施报告

## 概述

为 RAGNexus 异步索引后端（Phase 3-4）适配前端，实现文档状态轮询、文档/KB 的 CRUD 操作入口。

## 变更文件清单

### 修改 (6 files)

| 文件 | 变更内容 |
|------|---------|
| `admin/src/types/api.ts` | 新增 `DocStatus` 枚举、`DocumentDetail`、`UpdateKBRequest`、`KBDetail`、`UploadResult` 类型；`UploadDocResponse.data` 增加 `status` 字段；`UploadResultEntry.status` 增加 `'processing'` |
| `admin/src/utils/upload-queue.ts` | 检测 `res.data.status === 'processing'`，设置条目为 `status: 'processing'`，详情为"已提交，正在后台索引" |
| `admin/src/pages/upload-doc.tsx` | 上传完成后检测 `processing` 结果，弹出 Toast "已提交，正在后台索引" |
| `admin/src/pages/knowledge-file-tree.tsx` | 全面重写：DocRow 集成 StatusBadge + 3s 轮询 + 删除/重试按钮；KbRow 增加 KB 编辑/删除入口及对话框 |
| `admin/src/utils/upload-queue.test.ts` | 测试 mock 数据追加 `status` 字段 |
| `admin/src/pages/knowledge-file-tree.test.tsx` | 重写测试以匹配 2 级树结构（KB→文档），新增 service mock |

### 新建 (6 files)

| 文件 | 用途 |
|------|------|
| `admin/src/services/documentService.ts` | `deleteDocument`、`reindexDocument`、`fetchDocument` |
| `admin/src/services/knowledgeBaseService.ts` | `fetchKBDetail`、`updateKB`、`deleteKB` |
| `admin/src/components/StatusBadge.tsx` | PROCESSING=黄色旋转（Loader2）、SUCCESS=绿色对勾（Check）、FAILED=红色叉号（X） |
| `admin/src/components/ConfirmDialog.tsx` | 通用确认对话框，支持 destructive variant 和 loading 状态 |
| `admin/src/components/EditKnowledgeBaseDialog.tsx` | 编辑 KB name/description/settings（JSON textarea，含合法性校验） |
| `admin/src/pages/integration.test.tsx` | Task 5.9 集成测试：三页导航 + PROCESSING 轮询与按钮禁用验证 |

## 验收结果

- [x] TypeScript 编译通过 (`tsc --noEmit` 零错误)
- [x] 单元+集成测试: 5/6 测试文件通过 (37 个测试)
  - upload-queue.test.ts: 6 passed
  - upload-doc.test.ts: 12 passed
  - knowledge-file-tree.test.ts: 10 passed
  - integration.test.tsx: 7 passed (Task 5.9)
  - file-filter.test.ts: 2 passed
  - retrieve.test.tsx: 10/11 passed (1 pre-existing failure, unrelated)
- [x] StatusBadge 三种状态渲染正确（PROCESSING/SUCCESS/FAILED）
- [x] DocRow 对 PROCESSING 文档启动 3s 轮询（max 60 次 = 3 分钟）
- [x] PROCESSING 文档的删除按钮禁用，FAILED 文档显示重试按钮
- [x] KB 编辑/删除对话框功能完整（ConfirmDialog + EditKnowledgeBaseDialog）
- [x] **Task 5.9 集成测试覆盖**:
  - 三页导航：上传按钮→`/?kb_id=xxx`，检索按钮→`/retrieve?kb_id=xxx`，空状态→`/`
  - PROCESSING 轮询：3s 间隔 fetchDocument，SUCCESS 后停止（`advanceTimersByTimeAsync` 时钟验证）
  - 按钮逻辑：PROCESSING 删除 disabled，FAILED 重试可点击且触发 reindexDocument
  - SUCCESS 文档不显示重试按钮

## 关键设计决策

1. **轮询策略**: DocRow 组件内部管理轮询 lifecycle，使用 `useRef` 追踪轮询次数，`useEffect` cleanup 自动清理 interval。轮询结束时调用 `onDocChanged` 刷新列表数据。
2. **状态管理**: 文档状态通过 `currentStatus` 本地状态追踪，轮询更新后实时反映到 StatusBadge。
3. **类型安全**: `UploadDocResponse.data.status` 改为必需字段（`string`），与后端异步索引接口对齐。
4. **测试适配**: 原测试基于 3 级租户树（租户→KB→文档），现适配为 2 级（KB→文档），移除租户层级断言，StatusBadge 使用中文标签。
5. **集成测试**: 使用 `vi.useFakeTimers({ shouldAdvanceTime: true })` + `advanceTimersByTimeAsync` 精确控制轮询时钟，避免真实等待。
