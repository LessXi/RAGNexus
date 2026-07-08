# Task 11: 联调 & 验收

## 依赖
- Task 1-10 全部完成

## 目标
运行全量测试、E2E 验证、错误路径检查，确保整体功能可用。

## 验证清单

### 11.1 后端全量测试
```bash
pytest -v
```
所有后端单元+集成测试通过（含 rrf_fuse 新逻辑 + 分数合并用例）。

### 11.2 前端全量测试
```bash
cd admin && npx vitest run
```
所有前端 unit test 通过。

### 11.3 E2E 全链路验收
按 `docs/acceptance-criteria.md` 第四节 14 条验收标准逐条核对：

1. 打开 http://localhost:5173 → 显示首页（UploadDocPage + AppHeader）
2. 首页顶部「创建知识库」Card 可见，输入 tenant_id + name → 创建成功 → KB 下拉刷新
3. KB 下拉从 tree API 获取（不再依赖 localStorage）
4. 上传文档流程正常（选择 KB → 上传文件 → 显示成功）
5. 导航到 /knowledge-bases → 三级树正确渲染
6. 列表页搜索框按 tenant_id 过滤 → 结果正确
7. 列表页「复制 kb_id」→ toast 提示
8. 列表页「跳转上传」→ 带 kb_id 参数跳转
9. 列表页「跳转检索」→ 带 tenant_id + kb_id query params
10. /retrieve 页 → 检索配置 Card + 检索结果 Card + 运行摘要 Card
11. 检索配置：选择 mode=hybrid → hybrid 参数显示；选择 mode=vector → 隐藏
12. 检索执行：输入 query → 点击检索 → 结果显示（分数 chips + 可折叠内容）
13. 运行摘要：meta 字段正确展示
14. 列表页跳转到检索页 → URL query params 自动预填

### 11.4 回归验证
- 首页上传文档逻辑不受影响（已有上传测试）
- demo_retrieve.py 可正常运行（如需要更新则更新）
- 无控制台错误

### 11.5 错误路径
- API 5xx → 前端 toast 错误提示 + retry 按钮
- tree API 无数据 → 列表页显示空状态
- network error → 各页面降级提示
- 检索无结果 → 显示「无匹配结果」

## 全局约束
- 不修改源代码（本 task 只做验证）
- 发现问题需记录并回到对应 task 修复
