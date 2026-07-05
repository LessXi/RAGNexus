# Comet Artifacts 专项审查

## proposal.md

| # | 问题 | 等级 |
|---|---|---|
| 1 | "关掉浏览器就找不回建好的知识库" — 实际上当前 `getKBs()` 存在 localStorage 里，关掉浏览器**能**找回。痛点描述不完全准确——真正的问题是"换浏览器/换设备找不回"，这点文案建议改为"无法跨设备/跨会话查看已有知识库" | 🟢 nit |
| 2 | Capabilities 里 `document-upload` 标为 Modified，但实际上只是**前端页面**合并了创建 KB 表单，上传链路后端完全不变。是否该归为 New Capability 而非 Modified？毕竟 `document-upload` 的 spec-level 行为没变 | 🟡 |

## design.md

| # | 问题 | 等级 |
|---|---|---|
| 3 | D4 说「与旧 `_candidate_k` 参数向后兼容」，但 `_candidate_k` 是用例构造参数，不是 API 参数。向后兼容的对象说不清——是对旧 API 调用方兼容，还是对 composition.py 装配兼容？需明确 | 🟡 |
| 4 | D6 路由表说 `/` → UploadDocPage（含创建 KB），但 proposal 的 Capabilities 里 `document-upload` 是 Modified。如果创建 KB 是**移到**首页（不是新增），CreateKBPage 需要标记为 Removed。proposal 没提删除 | 🟡 |
| 5 | 风险表说「`total` 字段从 `data.total` 下沉到 `data.meta`」，但 api-spec 的新响应**根本没有** `total` 字段——既不在 `data` 也不在 `meta`。文档之间不一致 | 🔴 |
| 6 | Implementation Order 里「7. Create KB API tenant_id」放在第 7 位，但 migration（第 1 位）加了 `tenant_id` 列后，创建 KB 的代码如果不跟着更新就会**立即报错**（必填列没有默认值，migration 之后旧 create 代码会炸）。正确顺序：migration + create KB API 必须在同一批 | 🔴 |

## tasks.md

| # | 问题 | 等级 |
|---|---|---|
| 7 | 1.2/1.3/1.4/1.5 都在 DB 组里，但这几个 task 跨越了 4 个文件（repo / port / use case / router），应该拆分到 §1（DB 层）和 §1b（API 层）两个组 | 🟡 |
| 8 | 2.2 `rrf_fuse` 改造放在 §2 第一个，但它的改造依赖于 2.3 中 `_vector_score`/`_bm25_score` 已经写入。正确顺序：先 2.3 在 use case 里标记分数，再 2.2 让 rrf_fuse 合并 | 🔴 |
| 9 | 3.4 `composition.py` 更新是**冗余任务**——`create_retrieve_router(retrieve_uc)` 不需要改（router 是 factory，参数通过路由内部处理）。可以删掉 | 🟢 |
| 10 | §5 缺少「安装 shadcn table 组件」前置任务 | 🔴 |
| 11 | §9 「9.1 全量后端单元测试」放在最后，但按 TDD 应该在每步实现后立即跑对应测试。建议拆成 per-section 的验证任务 | 🟡 |
| 12 | 没有任何任务涉及「更新 KnowledgeBasePort protocol 增加 `list_with_documents`」——4.1 只在 ports 加签名，但 1.3 也要改 create 签名。两个 protocol 变更在同一个文件，应该合并为一步 | 🟡 |

---

## 汇总：必须立即修复的 🔴

| 修复 | 文件 | 操作 |
|---|---|---|
| api-spec 和 design 对 `total` 字段不一致 | design.md risk 行, api-spec | design: 删掉「`total` 下沉到 `data.meta`」的描述；api-spec: meta 加 `total` 字段 |
| migration 后 create KB 立即报错 | design.md order | 合并 item 1+7 为同一批次：「先跑 migration → 立刻更新 create 链路」 |
| tasks 2.2/2.3 顺序反了 | tasks.md | 交换 2.2 和 2.3，先标记分数再融合 |
| 缺 shadcn table 安装任务 | tasks.md | §5 开头加 `5.0 npx shadcn add table` |
