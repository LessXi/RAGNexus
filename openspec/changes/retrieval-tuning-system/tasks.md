# Tasks: 检索效果调优系统

## Phase 1: Langfuse 基础设施

- [x] 1.0 确认 Alembic 已初始化（否则先执行 alembic init）
- [x] 1.1 docker-compose.yml 新增 langfuse + langfuse-db service（含 NEXTAUTH_SECRET + langfusedata volume）
- [x] 1.2 config.py 新增 LANGFUSE_ENABLED/HOST/PUBLIC_KEY/SECRET_KEY 配置项
- [x] 1.3 .env 和 .env.example 补充 LANGFUSE_* 变量
- [x] 1.4 pyproject.toml 新增 langfuse>=2.0.0,<3.0.0 依赖
- [x] 1.5 新增 src/ragnexus/observability/__init__.py + langfuse_client.py（RetrieveObservability + get_langfuse_client() + 静默逻辑）
- [x] 1.6 composition.py 注入 langfuse_client 单例

## Phase 2: 检索可观测

- [x] 2.1 retrieve_router.py 包裹 trace（rag_retrieve + 3 个子 span）
- [x] 2.2 retrieve_router.py 用 nanoid 预生成 log_id，响应 metadata 新增 log_id + trace_id
- [x] 2.3 RetrieveResult/RetrieveMetadata schema 新增 log_id + trace_id 字段
- [x] 2.4 retrieval_logs 表扩展 5 列（log_id VARCHAR(24) UNIQUE + trace_id + profile + search_query + effective_query），Alembic migration 0006 + schema.sql
- [x] 2.5 PgRetrieveLogRepository 适配新字段写入（log PORT 扩展接口）
- [x] 2.6 frontend types/api.ts 同步 log_id + trace_id

## Phase 3: 反馈 API

- [x] 3.1 core/errors.py 新增 20020/20021/20022 错误码
- [x] 3.2 新增 schemas/feedback.py（FeedbackRequest, FeedbackData）
- [x] 3.3 新增 services/feedback_service.py（校验归属 + Langfuse score 写入，复用 get_langfuse_client()）
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
