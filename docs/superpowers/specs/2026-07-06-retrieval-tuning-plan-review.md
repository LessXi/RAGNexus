# 计划对抗性交叉评审

> 审阅对象: 实施计划 × Design Doc × tasks.md × 飞书文档 × 现有代码
> 方法: 逐任务验证可行性 + 依赖完整性 + 遗漏检查

---

## 🔴 阻塞级 (Blockers)

### B1. retrieval_logs 缺少 tenant_id 列 → feedback 校验无法实现

**计划 3.3**: "查 retrieval_logs 验证 tenant 匹配"
**计划 2.4**: migration 只加 5 列（log_id, trace_id, profile, search_query, effective_query）
**现有表**: retrieve_logs 只有 kb_ids TEXT[]，没有 tenant_id

**矛盾**: 要验证"当前租户是否拥有这条日志"，需要知道这条日志的 tenant_id。当前只能通过 `JOIN knowledge_bases ON kb.id = ANY(kb_ids)` 间接查——但跨 KB 查询时返回多个 tenant_id，无法判定。

**飞书文档明确要求**: "若传 log_id：查 retrieval_logs，校验 tenant_id 匹配且 trace_id 一致"

**修复**: migration 加第 6 列 `tenant_id TEXT`，INSERT 时从 TenantContext 获取，feedback 校验时直接 WHERE log_id=$1 AND tenant_id=$2。

### B2. 2.2 log_id 只改了 retrieve_router，没改 2.5 repo 接口

**计划 2.2**: "在 retrieve_router.py 用 nanoid 生成 log_id"
**计划 2.5**: "log() 方法新增 log_id 等字段的写入"
**gap**: 2.5 的 `log()` 方法接口需要新增 `log_id` 参数，但 `log()` 在 RetrieveUseCase 中被调用（不是 router），双方需要传递 log_id。

**修复**: 2.2 生成的 log_id 需要透传到 UC → 再透传到 `log_port.log(log_id=...)`。或者 router 直接调 log_port。需明确数据流。

---

## 🟠 高风险 (High Risk)

### H1. Phase 1 总标题写 6 任务，实际是 7 个

**标题**: "Phase 1: Langfuse 基础设施 (6 任务, ~2h)"
**实际**: 1.0 ~ 1.6 = 7 个任务
**影响**: 任务数对不上，但不影响执行。建议修正标题。

### H2. 2.1 trace 依赖 1.6，但 1.6 只管注入不保证 langfuse 可用

**计划 2.1**: 依赖 1.6（composition 注入单例）
**实际需要**: Langfuse 服务必须先启动（1.1），配置必须先写好（1.2/1.3）
**风险**: 如果 2.1 在 Langfuse 服务未就绪时写代码，验证只能在 Phase 6 做

**建议**: 2.1 的依赖标注增加 1.1（需要 Langfuse 服务运行才能验证）

### H3. 3.3 feedback_service 依赖 2.4（DB migration），但 2.4 依赖 1.0（Alembic）

**计划 3.3 依赖**: 1.5, 2.4, 3.1, 3.2
**遗漏**: 2.4 本身依赖 1.0（Alembic 初始化），这个传递依赖未标注

**影响**: 如果 Alembic 未初始化，整个 Phase 3 都会阻塞，但排查链较长

### H4. 缺少 Dockerfile 或 docker-compose 的 Langfuse 健康检查依赖声明

**计划 1.1**: 提到 healthcheck，但没说 app service 是否要 `depends_on: langfuse`
**设计明确**: Langfuse 是可选旁路，app 不应依赖它
**但**: 如果加了 `depends_on`，app 启动会等 Langfuse 就绪——这是错误的

**建议**: 1.1 明确标注 "不加 depends_on，Langfuse 离线不影响 app"

---

## 🟡 中风险 (Medium Risk)

### M1. 5.6 export 脚本依赖标注为 Phase 3，实际需要 Phase 2+3

**依赖**: Phase 3（需 feedback 数据沉淀）
**遗漏**: 也需要 Phase 2（可观测），因为 export 要读 Langfuse trace 的 metadata.kb_id 和 log_id

### M2. 预估可能偏低

| 任务 | 计划 | 实际可能 |
|---|---|---|
| 2.1 trace 包裹 | 60min | 90min（需理解现有 router + 调试 Langfuse SDK） |
| 4.3 反馈条组件 | 60min | 90min（shadcn 组件集成 + 响应式布局） |
| 5.7 eval 脚本 | 45min | 60min（RAGAS API 适配 + LLM 配置调试） |

### M3. 缺少 langfuse_client 单元测试任务

**Phase 1 验证**: "单元测试覆盖开关逻辑"
**但**: 没有独立的任务创建测试文件
**对比**: Phase 3 有 3.6 专门的测试任务

**建议**: Phase 1 增加 1.7 单元测试任务，或在 1.5 中明确包含测试

### M4. 2.3 Schema 更新定位不准确

**计划 2.3**: "RetrieveResult/RetrieveMetadata 新增字段，文件 domain/models.py"
**实际**: 当前 RetrieveResult 在 models.py:91，返回给 router。但 metadata 字段（log_id/trace_id）不一定加在 RetrieveResult 上——router 层直接构造响应 dict，不经过 domain model

**建议**: 明确是加在 router 的响应构造中（retrieve_router.py 的返回 dict），还是加在 domain model 上

---

## 🔵 低风险 (Low Risk)

### L1. Phase 6 验收依赖标注不完整

**6.3 E2E 可观测验收**: 依赖 Phase 2，但实际需要 docker-compose 启动 Langfuse（1.1）
**6.5 离线测评验收**: 依赖 Phase 5，但实际需要 Phase 2（可观测）才能让 eval 脚本通过 retrieve 拿到结果

### L2. 4.1 依赖 3.2 但 3.2 是后端 Python schema

**计划 4.1**: types/api.ts 依赖 3.2（feedback.py Pydantic schema）
**实际**: 前端 TS 类型和后端 Pydantic 是两个独立定义，不需要代码级依赖。逻辑上需要对齐，但标注为"依赖"容易产生串行执行的错觉

### L3. 缺少 git commit 策略

**计划**: 无提及何时提交、提交粒度
**建议**: 每个任务完成后 git commit，message 含任务编号

---

## 📊 评审统计

| 级别 | 数量 | 关键发现 |
|---|---|---|
| 🔴 阻塞 | 2 | tenant_id 缺失、log_id 传递路径 |
| 🟠 高风险 | 4 | 任务数错误、依赖标注、healthcheck |
| 🟡 中风险 | 4 | 依赖遗漏、预估偏低、测试缺失、schema 定位 |
| 🔵 低风险 | 3 | 验收依赖、串行误解、commit 策略 |

**总计**: 13 个发现。B1（tenant_id）和 B2（log_id 传递）为全新盲区。
