# 对抗性交叉评审报告

> Change: retrieval-tuning-system
> 审阅范围: proposal.md + design.md + tasks.md + Design Doc + 飞书原始文档
> 方法: 交叉比对 + 边界条件攻击 + 缺失路径枚举

---

## 🔴 阻塞级 (Blockers)

### B1. log_id 返回时序问题

**proposal.md**: "响应新增 log_id + trace_id"
**design.md**: log_id = retrieval_logs.id (BIGSERIAL)
**现有代码**: retrieve_router.py 中 `_safe_log()` 是异步 fire-and-forget 后台任务，log 的 INSERT 和响应返回是并发的

**矛盾**: log_id 是 INSERT 时由 PostgreSQL 生成的 BIGSERIAL。如果 INSERT 是后台异步任务，响应返回时 log_id 尚不存在。

**飞书文档要求**: "log_id 是本次检索的唯一标识，与 retrieval_logs 表主键一致"

**修复方案**: retrieve_router 中 retrieval_logs 的 INSERT 必须改为同步写入（在返回响应前完成），或预生成 UUID 作为 log_id（不使用 BIGSERIAL 自增）。

### B2. docker-compose 缺少 NEXTAUTH_SECRET

**飞书文档**: "须配置 NEXTAUTH_URL=http://localhost:3000 和 ENCRYPTION_KEY"
**design.md / tasks.md**: 未明确提及 NEXTAUTH_SECRET
**Langfuse v2 实际要求**: 需要 NEXTAUTH_SECRET（NextAuth 必需），缺少则 Langfuse 无法启动（白屏/500）

**修复**: docker-compose langfuse service 须加 `NEXTAUTH_SECRET` 环境变量。

---

## 🟠 高风险 (High Risk)

### H1. 缺少 Alembic 初始化验证

**tasks.md**: "2.4 retrieval_logs 表扩展 4 列（Alembic migration 0006 + schema.sql）"
**项目现状**: pyproject.toml 有 alembic 依赖，但项目通过 init-db 容器直接执行 schema.sql，Alembic 的 migrations/ 目录是否已初始化未知

**风险**: 如果 alembic 从未 init，需要先 `alembic init` + 配置 alembic.ini + 创建 env.py，才能运行 migration

**建议**: Phase 1 新增前置任务 "确认 Alembic 已初始化或先执行 alembic init"

### H2. Feedback API 的 Langfuse client 复用机制未明确

**飞书文档**: "复用 app/observability/langfuse_client.get_langfuse_client()，不重复创建 client"
**design.md**: Feedback service 使用 Langfuse SDK create_score
**缺失**: langfuse_client.py 需暴露 `get_langfuse_client()` 函数返回已初始化的 client 实例

**建议**: tasks.md 1.5 描述补充 "含 get_langfuse_client() 导出函数，供 feedback_service 复用"

### H3. 前端 feedback 失败路径未覆盖

**飞书文档验收标准**:
- "LANGFUSE_ENABLED=false 时调 feedback → 20020，调试台反馈条不可用"
- "提交成功 → 简短提示「已提交」"

**缺失场景**:
- 提交 feedback 时网络中断 → 用户看到什么？
- 20021（无权）→ 前端如何提示？
- 20020（Langfuse 不可用）→ 前端提示差异？
- 提交中（loading 状态）→ 按钮禁用 + spinner？

**建议**: tasks.md 4.4 细化：loading 状态 + 错误提示差异化（20020/20021/20022/网络错误四种）

---

## 🟡 中风险 (Medium Risk)

### M1. docker-compose volume 声明遗漏

**tasks.md 1.1**: "docker-compose.yml 新增 langfuse + langfuse-db service"
**遗漏**: `volumes:` 节需新增 `langfusedata:`

### M2. observability/__init__.py 遗漏

**新增文件清单**: 只列了 `observability/langfuse_client.py`
**遗漏**: `observability/__init__.py`

### M3. eval 脚本的 API Key 来源未明确

**设计**: eval 脚本通过 Bearer Token 调 retrieve API
**缺失**: API Key 需提前用 `scripts/create_api_key.py` 创建，脚本的 `--api-key` 参数无默认值

**建议**: tasks.md Phase 5 新增 "创建 eval 专用 API Key" 子任务

### M4. LANGFUSE_ENABLED 边界行为未文档化

**验收标准**: true/false 两个场景都测
**缺失边界**:
- LANGFUSE_ENABLED=true 但 Langfuse 服务未启动 → 行为？
- LANGFUSE_ENABLED=true 但 PUBLIC_KEY 为空 → 行为？

**建议**: 设计明确：这两种情况 trace 创建静默失败（try/catch + warning 日志），不抛异常

---

## 🔵 低风险 / 建议 (Low Risk)

### L1. 缺少回滚/清理任务

28 个任务，无回滚方案。若 Alembic migration 失败需手动处理。

### L2. feedback_id 来源不明确

FeedbackData 含 feedback_id。是 Langfuse SDK 返回值还是自定义生成？未启用时 feedback_id 是什么？

### L3. tasks.md Phase 4 和 Phase 5 依赖标注

Phase 5 export 脚本需要 Phase 3 的 feedback API 上线后才能收集真实反馈数据。当前未标注此依赖。

---

## 📊 评审统计

| 级别 | 数量 | 关键发现 |
|---|---|---|
| 🔴 阻塞 | 2 | log_id 时序、NEXTAUTH_SECRET |
| 🟠 高风险 | 3 | Alembic 初始化、client 复用、前端错误路径 |
| 🟡 中风险 | 4 | volume 声明、__init__.py、API Key、边界行为 |
| 🔵 低风险 | 3 | 回滚、feedback_id、依赖标注 |

**总计**: 12 个发现。B1 和 B2 必须在 build 前解决。
