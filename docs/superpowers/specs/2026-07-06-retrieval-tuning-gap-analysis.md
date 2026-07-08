# 逐节需求对照分析

## 文档1: 为什么需要效果调优与工具选型

| 节 | 需求 | 设计覆盖 | 状态 |
|---|---|---|---|
| 三角闭环 | 可观测 + 可反馈 + 离线测评 | ✅ 三个模块已设计 | OK |
| 工具选型 | Langfuse + RAGAS，分工不重叠 | ✅ | OK |
| 工具对比 | LangSmith(拒)/Arize(备)/DeepEval(拒) | ✅ 记录为边界 | OK |
| 核心能力 | retrieve/log_id/trace_id/retrieval_logs 不替换 | ✅ | OK |
| 完整流程 | retrieve→返回→Langfuse→logs→反馈→RAGAS | ✅ | OK |

## 文档2: 检索可观测的提示词

| 节 | 需求 | 设计覆盖 | 状态 |
|---|---|---|---|
| 依赖 | langfuse>=2.0.0,<3.0.0 | ✅ pyproject.toml | OK |
| 配置 | 4个 LANGFUSE_* 字段 | ✅ config.py | OK |
| docker-compose | langfuse-db(独立PG库名langfuse)+langfuse(:2, :3000) | ✅ NEXTAUTH_URL+NEXTAUTH_SECRET+ENCRYPTION_KEY | OK |
| 封装 | app/observability/langfuse_client.py | ✅ | OK |
| 静默 | LANGFUSE_ENABLED=false → 无操作，get_langfuse()→None | ✅ | OK |
| 埋点 | trace名rag_retrieve, metadata含5字段 | ✅ | OK |
| span1 | query_processing: 原始query/effective_query/同义词 | ✅ | OK |
| span2 | retrieval: mode/vector命中/bm25命中/hybrid降级 | ✅ | OK |
| span3 | rerank: 启用/候选数/降级 | ✅ | OK |
| trace output | 只存chunk_id+score摘要，不塞全文 | ✅ | OK |
| 失败处理 | 写入失败→warning，不影响返回 | ✅ | OK |
| 响应 | metadata加log_id+trace_id | ✅ RetrieveMetadata | OK |
| 表扩展 | Alembic 0006, 4字段均可空 | ✅ | OK |
| Schema | RetrieveMetadata新增 | ✅ | OK |
| 反馈API | POST /api/v1/rag/feedback, Depends(get_current_tenant) | ✅ | OK |
| 反馈Schema | trace_id(必)/log_id(建议)/score(1~5)/comment(否) | ✅ | OK |
| 反馈响应 | FeedbackData: feedback_id/trace_id/log_id/score | ✅ | OK |
| Service | 3步:校验→score→复用client | ✅ | OK |
| 错误码 | 20020/20021/20022 | ✅ | OK |
| 前端 | 检索结果区/五星/备注/提交/清空 | ✅ | OK |
| 前端细节 | 无trace_id→隐藏+提示/提交必选/成功提示/再次检索清空 | ✅ | OK |
| 前端组件 | shadcn Card/Button/Textarea | ✅ | OK |
| 前端API | ragService.submitFeedback()+FeedbackRequest/FeedbackData | ✅ | OK |
| 文档 | tenant-onboarding.md加小节 | ✅ | OK |
| 边界 | 不建feedbacks表/不做RAGAS/不做历史查询/不做大盘 | ✅ | OK |
| 边界 | body多传→Pydantic忽略 | ✅ extra=forbid | OK |

## 文档3: 离线测评的提示词

| 节 | 需求 | 设计覆盖 | 状态 |
|---|---|---|---|
| 依赖 | ragas>=0.2.0, datasets>=2.0.0 in optional-deps[eval] | ✅ | OK |
| LLM配置 | MODEL_BASE_URL/MODEL_API_KEY→实际字段是LLM_BASE_URL/LLM_API_KEY | ⚠️ 需适配字段名 | **GAP** |
| 目录 | eval/datasets/ (3文件) + eval/reports/ | ✅ | OK |
| golden set | JSON结构: name/kb_id/default_profile/cases[] | ✅ | OK |
| case字段 | question(必)/ground_truth(评前必)/id(建议lf_)/source | ✅ | OK |
| skip | ground_truth为空→自动skip+提示 | ✅ | OK |
| export脚本 | 读.env LANGFUSE_*, 拉score≤threshold, 关联trace | ✅ | OK |
| export细节 | --merge按question去重, 已有ground_truth不覆盖, 打印统计 | ✅ | OK |
| export代理 | httpx关闭系统代理 | ✅ | OK |
| export参数 | 5个argparse参数(--max-score/--days/--kb-id/--output/--merge) | ✅ | OK |
| eval脚本 | 读golden set, skip空, 逐条调retrieve, RAGAS只评2指标 | ✅ | OK |
| eval细节 | context_recall偏低单独列出, --output写JSON | ✅ | OK |
| eval user_id | 固定eval_runner, 区分评测流量 | ⚠️ API无user_id字段 | **GAP** |
| eval请求格式 | kb_id(单数)+user_id → 实际API是kb_ids(复数) | ⚠️ 字段名不一致 | **GAP** |
| eval参数 | 5个argparse参数(--dataset/--api-key/--base-url/--profile/--output) | ✅ (base-url改为读.env) | OK |
| 衔接 | 每次重跑, ground_truth不变, 多profile对比 | ✅ | OK |
| 文档 | README加离线测评小节, tenant-onboarding链到eval/ | ⚠️ 内容需补全 | **GAP** |
| 种子文件 | _seed_ecommerce.json对齐data/ecommerce/文档 | ⚠️ data/目录不存在 | **GAP** |
| 边界 | 不建feedbacks表, 脚本独立, ground_truth不自动填 | ✅ | OK |
| 边界 | faithfulness等需要生成答案的指标不在范围 | ✅ | OK |
| .gitignore | eval/reports/加入 | ✅ | OK |
| 验收6条 | export/人工补/eval指标/skip/对比/缺key友好报错 | ✅ | OK |

## 🔴 发现的 5 个 GAP

### GAP 1: retrieve API 缺少 user_id 字段
**文档要求**: eval脚本调用 retrieve 时传 user_id="eval_runner"，用于在 Langfuse 区分评测流量
**现状**: _RetrieveRequest 没有 user_id 字段，TenantContext 也没有 user_id
**解决方案**: 在 _RetrieveRequest 新增可选字段 user_id: str | None = None，透传到 trace metadata

### GAP 2: eval 脚本字段名不一致
**文档要求**: 请求体用 kb_id(单数) + user_id
**现状**: API 用 kb_ids(复数列表)
**解决方案**: eval脚本适配，传 kb_ids=["<kb_id>"]，user_id 作为请求体可选字段

### GAP 3: RAGAS LLM 配置字段名映射
**文档要求**: eval脚本读 .env 的 MODEL_BASE_URL 和 MODEL_API_KEY
**现状**: config.py 中字段名为 LLM_BASE_URL 和 LLM_API_KEY
**解决方案**: eval脚本直接读 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL，不从 config.py 引入

### GAP 4: data/ecommerce/ 目录不存在
**文档要求**: _seed_ecommerce.json 对齐 data/ecommerce/ 文档
**现状**: 项目无 data/ 目录
**解决方案**: 冷启动种子从项目现有测试文档中手工构造 5~10 条，不依赖 data/ 目录

### GAP 5: README 离线测评内容
**文档要求**: README 增加「离线测评」小节
**现状**: 设计覆盖但内容未细化
**解决方案**: 实现时补充: export → 补ground_truth → run eval 三步流程说明
