# Brainstorm Summary

- Change: retrieval-tuning-system
- Date: 2026-07-06

## 确认的技术方案

采用 **Langfuse 旁路 + RAGAS 独立脚本** 架构：

1. **可观测层**：Langfuse 作为 fire-and-forget 旁路，在 retrieve_router 层包裹 trace（1 trace + 3 spans），不侵入 RetrieveUseCase 代码。`LANGFUSE_ENABLED=false` 时整个可观测层静默。

2. **双链 ID**：`log_id`（retrieval_logs.id，永远有值）供业务方关联流水；`trace_id`（Langfuse 生成）供研发在面板定位详情。

3. **反馈 API**：`POST /v1/rag/feedback`，复用现有 Bearer Token 鉴权，校验 log_id 归属后写 Langfuse score。不建本地 feedbacks 表。

4. **离线测评**：2 个独立 Python 脚本，通过 HTTP 调 retrieve API。export 脚本从 Langfuse 拉低分 case，eval 脚本用 RAGAS 计算 context_precision + context_recall。

5. **身份模型**：保持租户中心架构。eval 通过独立 API Key（租户标识 eval_runner）区分评测流量，不引入 user_id 概念。

6. **DB 扩展**：retrieval_logs 加 4 列（trace_id, profile, search_query, effective_query），Alembic migration + schema.sql 双写，新列均可空。

## 关键取舍与风险

| 取舍 | 理由 |
|---|---|
| Langfuse 自托管 vs 云服务 | 数据安全，不传出内网 |
| fire-and-forget vs 同步写入 | 不增加检索延迟 |
| Langfuse SDK vs 裸 httpx | SDK 功能完整，减少维护成本 |
| 不建 feedbacks 表 | 避免双写同步，Langfuse 是唯一真相源 |
| trace 在 router 层 vs use case 层 | 不侵入业务逻辑，职责清晰 |

| 风险 | 缓解 |
|---|---|
| Langfuse 高并发写入瓶颈 | 异步 flush + 失败只打 warning |
| SDK 代理冲突 | httpx.Client(trust_env=False) |
| 表扩展影响旧数据 | 新列均可空 |
| eval 依赖冲突 | optional-dependencies[eval] 独立安装 |

## 测试策略

- langfuse_client：单元测试 mock SDK，验证开关逻辑
- retrieve_router trace：集成测试验证响应字段
- feedback API：单元测试覆盖正常/越界/无权限/Langfuse 关闭
- 前端反馈条：E2E 选星→提交→验证
- eval 脚本：集成测试 dry-run

## Spec Patch

无。本 change 全部是新 capability，不修改现有 OpenSpec specs。
