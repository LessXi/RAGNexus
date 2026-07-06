# Proposal: 检索效果调优系统

## 问题

RAGNexus 的检索链路当前是一个黑盒：
- **不可观测**：只记录最终结果到 `retrieval_logs`（8 个基础字段），无法复盘中间过程
- **不可反馈**：没有反馈入口，线上问题沉淀不下来
- **不可测评**：没有量化评估体系，调参靠感觉，不敢发版

线上每天跑几百上千次检索，运营和研发需要能统计、能回看、能持续优化的数据。

## 目标

建立检索效果调优的**三角闭环**：

| 能力 | 目标 | 工具 |
|---|---|---|
| 可观测 | 每次检索在 Langfuse 留下完整 trace，记录改写→召回→重排全过程 | Langfuse（自托管） |
| 可反馈 | 提供反馈 API + 调试台五星评分，让低质检索能被标记和复盘 | Langfuse Scores |
| 离线测评 | 用 RAGAS 批量跑 golden set，量化 context_precision + context_recall | RAGAS |

三者串起来：可观测记录现场 → 反馈收集评分 → 离线测评量化效果 → 改配置 → 再测 → 上线。

## 范围

### 涉及
- `retrieve_router.py`：包裹 Langfuse trace（fire-and-forget），响应新增 `log_id` + `trace_id`
- `retrieval_logs` 表：扩展 4 列（trace_id, profile, search_query, effective_query）
- 新增 `POST /v1/rag/feedback`：反馈 API
- 新增 Admin 前端反馈条：五星评分 + 备注
- 新增 `eval/` 目录 + 2 个脚本：export 低分 case、RAGAS 批量评测
- docker-compose：新增 langfuse + langfuse-db 两个 service
- 配置：新增 4 个 LANGFUSE_* 环境变量

### 不涉及
- 不建 `feedbacks` 表（Langfuse 是反馈唯一真相源）
- 不做历史查询 API（直接用 Langfuse UI）
- 不做 Langfuse 统计大盘
- 不做完整问答链路评测（faithfulness/answer_relevancy 不在范围）
- 不替换现有 retrieve 接口契约
- 不修改 upload/kb/document 等其他路由

## 非目标
- 不接入 LangSmith/Arize/DeepEval 等替代工具
- 不在 Celery worker 中做可观测埋点
- 不做租户级套餐限制（可观测是基础设施能力）
