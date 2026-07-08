# Comet Design Handoff

- Change: retrieval-tuning-system
- Phase: design
- Mode: compact
- Context hash: 802b3a3d484326b52bbba732e051bf7c0a23341c3ceffec6679a59d6f1e564e4

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/retrieval-tuning-system/proposal.md

- Source: openspec/changes/retrieval-tuning-system/proposal.md
- Lines: 1-46
- SHA256: 28fc00421b80c107efc0c220a4269c9f7dca2eb2117c2083df51f39426fc893a

```md
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
```

## openspec/changes/retrieval-tuning-system/design.md

- Source: openspec/changes/retrieval-tuning-system/design.md
- Lines: 1-103
- SHA256: 56e4f314d7c0939818013b1a87976d5eae2447dc99142f1831ae74297b436adf

[TRUNCATED]

```md
# Design: 检索效果调优系统

## 架构决策

### 1. Langfuse 是旁路，不是主链路

Langfuse trace 写入采用 **fire-and-forget** 模式：
- 请求返回前启动异步 flush，不阻塞检索响应
- 写入失败只打 warning 日志，不影响 retrieve 正常返回
- `LANGFUSE_ENABLED=false` 时整个可观测层静默

### 2. 双链 ID 设计（已修正 B1）

| ID | 来源 | 生成方式 | 用途 |
|---|---|---|---|
| `log_id` | nanoid 本地预生成 | `"log_" + nanoid(12)`，纯内存 0ms | 业务方关联流水，**永远有值** |
| `trace_id` | Langfuse SDK 生成 | Langfuse trace 创建时返回 | 研发面板定位，**Langfuse 未启用时为 null** |

**第一性原理**: log_id 的本质是"响应时刻就能确定的唯一标识"，不应依赖 DB 的 BIGSERIAL。用 nanoid 本地预生成，INSERT 保持 fire-and-forget，不改 PK 类型。

`retrieval_logs` 表新增 `log_id VARCHAR(24) UNIQUE` 列（与 PK `id` 分离），旧数据 NULL。

### 3. Trace 结构

```
trace: "rag_retrieve"
├── metadata: {tenant_id, kb_ids, profile, plan}
├── span: query_processing    (原始query → LLM改写 → 词表扩展)
├── span: retrieval           (mode, vector/bm25命中数, 降级标记)
├── span: rerank              (启用/候选数/降级标记)
└── output: [{chunk_id, score}, ...]  (只存摘要，不塞全文)
```

### 4. 反馈链路

```
Admin UI → POST /v1/rag/feedback
  → 校验 TenantContext (Bearer Token)
  → 若传 log_id: 查 retrieval_logs 校验归属
  → Langfuse SDK create_score(name="user_feedback", value=1~5)
  → 返回 feedback_id
```

### 5. 离线测评独立运行

```
脚本1: export_eval_cases_from_langfuse.py
  → 读 .env LANGFUSE_* → 拉 score ≤ threshold 的反馈
  → 关联 trace 提取 question → 输出 JSON (ground_truth 留空)
  → 支持 --merge 去重追加

脚本2: run_retrieval_eval.py
  → 读 golden set JSON → 逐条调 POST retrieve
  → RAGAS 计算 context_precision + context_recall
  → 输出 JSON 报告
```

两个脚本独立运行，不嵌 FastAPI，不建新表。

### 6. 新增文件

| 文件 | 说明 |
|---|---|
| `src/ragnexus/observability/__init__.py` | 模块入口 |
| `src/ragnexus/observability/langfuse_client.py` | Langfuse SDK 封装，含 get_langfuse_client() 导出 |
| `src/ragnexus/schemas/feedback.py` | FeedbackRequest, FeedbackData |
| `src/ragnexus/services/feedback_service.py` | 反馈业务逻辑 |
| `src/ragnexus/adapters/http/feedback_router.py` | POST /v1/rag/feedback |
| `scripts/export_eval_cases_from_langfuse.py` | 导出低分 case |
| `scripts/run_retrieval_eval.py` | RAGAS 批量评测 |

### 7. 错误码新增

| code | HTTP | 含义 |
|---|---|---|
| 20020 | 503 | 反馈服务不可用 |
| 20021 | 403 | 无权操作该反馈记录 |
| 20022 | 422 | 评分超出允许范围(1-5) |

### 8. 新增目录
```

Full source: openspec/changes/retrieval-tuning-system/design.md

## openspec/changes/retrieval-tuning-system/tasks.md

- Source: openspec/changes/retrieval-tuning-system/tasks.md
- Lines: 1-54
- SHA256: cd1bea93ef6d0d3f64d6926983922cd80e9af0cdb3c7350e7498742e8384fff5

```md
# Tasks: 检索效果调优系统

## Phase 1: Langfuse 基础设施

- [ ] 1.0 确认 Alembic 已初始化（否则先执行 alembic init）
- [ ] 1.1 docker-compose.yml 新增 langfuse + langfuse-db service（含 NEXTAUTH_SECRET + langfusedata volume）
- [ ] 1.2 config.py 新增 LANGFUSE_ENABLED/HOST/PUBLIC_KEY/SECRET_KEY 配置项
- [ ] 1.3 .env 和 .env.example 补充 LANGFUSE_* 变量
- [ ] 1.4 pyproject.toml 新增 langfuse>=2.0.0,<3.0.0 依赖
- [ ] 1.5 新增 src/ragnexus/observability/__init__.py + langfuse_client.py（RetrieveObservability + get_langfuse_client() + 静默逻辑）
- [ ] 1.6 composition.py 注入 langfuse_client 单例

## Phase 2: 检索可观测

- [ ] 2.1 retrieve_router.py 包裹 trace（rag_retrieve + 3 个子 span）
- [ ] 2.2 retrieve_router.py 用 nanoid 预生成 log_id，响应 metadata 新增 log_id + trace_id
- [ ] 2.3 RetrieveResult/RetrieveMetadata schema 新增 log_id + trace_id 字段
- [ ] 2.4 retrieval_logs 表扩展 5 列（log_id VARCHAR(24) UNIQUE + trace_id + profile + search_query + effective_query），Alembic migration 0006 + schema.sql
- [ ] 2.5 PgRetrieveLogRepository 适配新字段写入（log PORT 扩展接口）
- [ ] 2.6 frontend types/api.ts 同步 log_id + trace_id

## Phase 3: 反馈 API

- [ ] 3.1 core/errors.py 新增 20020/20021/20022 错误码
- [ ] 3.2 新增 schemas/feedback.py（FeedbackRequest, FeedbackData）
- [ ] 3.3 新增 services/feedback_service.py（校验归属 + Langfuse score 写入，复用 get_langfuse_client()）
- [ ] 3.4 新增 adapters/http/feedback_router.py（POST /v1/rag/feedback）
- [ ] 3.5 composition.py 注册 feedback_router
- [ ] 3.6 单元测试：正常/20020/20021/20022 四场景

## Phase 4: 前端反馈条

- [ ] 4.1 types/api.ts 新增 FeedbackRequest, FeedbackData 类型
- [ ] 4.2 ragService.ts 新增 submitFeedback() 方法
- [ ] 4.3 RetrievePage 新增五星反馈条组件（Card 内 chunk 列表上方，shadcn Card/Button/Textarea）
- [ ] 4.4 交互逻辑：显示条件(trace_id非空)/星级点击(黄灰)/备注/提交(loading+成功+错误)/清空(再次检索)

## Phase 5: 离线测评脚本

- [ ] 5.1 pyproject.toml optional-dependencies 新增 eval 组（ragas>=0.2.0 + datasets>=2.0.0）
- [ ] 5.2 新建 eval/datasets/ 和 eval/reports/ 目录，.gitignore 新增 eval/reports/
- [ ] 5.3 新建 data/ecommerce/ 目录 + 种子文档
- [ ] 5.4 新建 eval/datasets/_seed_ecommerce.json（5~10 条手工种子）
- [ ] 5.5 用 create_api_key.py 创建 eval 专用 API Key（租户名 eval_runner）
- [ ] 5.6 新建 scripts/export_eval_cases_from_langfuse.py（5 个 argparse 参数，--merge 去重，httpx trust_env=False）
- [ ] 5.7 新建 scripts/run_retrieval_eval.py（读 golden set → 调 retrieve → RAGAS 计算 → 输出报告，context_recall 偏低单独列出）

## Phase 6: 文档与验收

- [ ] 6.1 docs/tenant-onboarding.md 新增「检索反馈」小节
- [ ] 6.2 README 新增「离线测评」小节（export → 补 ground_truth → run eval 三步）
- [ ] 6.3 端到端验收：LANGFUSE_ENABLED=true/false 场景（15 项验收标准）
- [ ] 6.4 反馈 API 验收：正常/错误 log_id/score 越界/Langfuse 关闭
- [ ] 6.5 离线测评验收：export + 补 ground_truth + eval + 对比
```

