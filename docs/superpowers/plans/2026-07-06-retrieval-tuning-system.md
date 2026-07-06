---
change: retrieval-tuning-system
design-doc: docs/superpowers/specs/2026-07-06-retrieval-tuning-system-design.md
base-ref: 899d015211439ecf263b903b7ec6b36cdc0541fa
---

# 检索效果调优系统 — 实施计划

## Phase 1: Langfuse 基础设施 (7 任务, ~2.5h)

### 1.0 确认 Alembic 初始化
- **目标**: 确保 `alembic` 已 init，`migrations/` 目录可用
- **文件**: `alembic.ini`, `migrations/env.py`
- **依赖**: 无
- **验证**: `alembic current` 不报错
- **预估**: 15min

### 1.1 docker-compose 新增 langfuse 服务
- **目标**: 添加 langfuse + langfuse-db service + langfusedata volume
- **文件**: `docker-compose.yml`
- **要点**: NEXTAUTH_URL, NEXTAUTH_SECRET, ENCRYPTION_KEY, 独立 Postgres 库名 langfuse, :3000 端口, healthcheck
- **依赖**: 1.0（无直接依赖，并行）
- **验证**: `docker compose up -d langfuse` → Langfuse UI 可访问
- **预估**: 20min

### 1.2 config.py 新增配置项
- **目标**: Settings 类新增 4 个 LANGFUSE_* 字段
- **文件**: `src/ragnexus/config.py`
- **依赖**: 1.1
- **验证**: `get_settings()` 可读取新字段
- **预估**: 10min

### 1.3 .env 和 .env.example 补充变量
- **目标**: 添加 LANGFUSE_* 变量及说明
- **文件**: `.env`, `.env.example`
- **依赖**: 1.2
- **验证**: grep LANGFUSE .env 输出 4 行
- **预估**: 10min

### 1.4 pyproject.toml 新增依赖
- **目标**: 添加 `langfuse>=2.0.0,<3.0.0`
- **文件**: `pyproject.toml`
- **依赖**: 无
- **验证**: `pip install -e .` 成功
- **预估**: 5min

### 1.5 新增 observability 模块
- **目标**: 创建 `langfuse_client.py`（RetrieveObservability + get_langfuse_client() + 静默逻辑）
- **文件**: `src/ragnexus/observability/__init__.py`, `langfuse_client.py`
- **要点**: LANGFUSE_ENABLED=false → 所有方法 noop；trace 创建 try/catch + warning；httpx trust_env=False
- **依赖**: 1.2, 1.4
- **验证**: 单元测试覆盖开关逻辑
- **预估**: 45min

### 1.6 composition.py 注入单例
- **目标**: lifespan 中初始化 langfuse_client，注入到需要的地方
- **文件**: `src/ragnexus/composition.py`
- **依赖**: 1.5
- **验证**: 应用启动无 import 错误，LANGFUSE_ENABLED=false 时静默
- **预估**: 15min

---

## Phase 2: 检索可观测 (6 任务, ~3h)

### 2.1 retrieve_router.py 包裹 trace
- **目标**: 在 `retrieve()` 函数中包裹 Langfuse trace，3 个子 span 记录全过程
- **文件**: `src/ragnexus/adapters/http/retrieve_router.py`
- **要点**: trace "rag_retrieve", metadata 含 tenant_id/kb_ids/profile/plan, 子 span 从 UC 返回值提取信息
- **依赖**: 1.6
- **验证**: LANGFUSE_ENABLED=true → Langfuse UI 可见 trace + 3 spans
- **预估**: 60min

### 2.2 log_id 预生成 + 响应字段 + 数据流
- **目标**: 用 nanoid 生成 log_id，透传到 UC → log_port → retrieval_logs，响应 metadata 加 log_id + trace_id
- **文件**: `retrieve_router.py`, `retrieve_use_case.py`（log_id 参数透传）
- **要点**: router 生成 `"log_" + nanoid(12)` → 传入 `uc.execute(log_id=...)` → UC 传入 `log_port.log(log_id=...)`；log_port 接口新增 log_id 参数
- **依赖**: 2.1
- **验证**: 响应含非空 log_id，DB 中 log_id 匹配
- **预估**: 30min

### 2.3 Schema 更新
- **目标**: RetrieveResult/RetrieveMetadata 新增 log_id + trace_id 字段
- **文件**: `src/ragnexus/domain/models.py`（如 RetrieveResult），或新建 schema
- **依赖**: 2.2
- **验证**: 类型检查通过
- **预估**: 15min

### 2.4 retrieval_logs 表扩展
- **目标**: Alembic migration 0008 新增 6 列 + schema.sql 同步
- **文件**: `alembic/versions/0008_retrieval_log_observability.py`, `docs/sql/schema.sql`
- **要点**: log_id VARCHAR(24) UNIQUE, tenant_id TEXT, trace_id VARCHAR(64), profile VARCHAR(32), search_query TEXT, effective_query TEXT；均可空；tenant_id 从 TenantContext 获取，供 feedback 校验租户归属
- **依赖**: 1.0（Alembic 就绪）
- **验证**: `alembic upgrade head` 成功，`\\d retrieve_logs` 显示 6 个新列
- **预估**: 20min

### 2.5 PgRetrieveLogRepository 适配
- **目标**: `log()` 方法接口新增 log_id + tenant_id + trace_id + profile + search_query + effective_query 参数，INSERT 写入所有新字段
- **文件**: `src/ragnexus/adapters/retrieve_log/pg.py`, `src/ragnexus/domain/ports.py`（RetrieveLogPort 接口扩展）
- **要点**: log_id 由 router 生成后传入，tenant_id 从 TenantContext 获取后传入；保持 try/catch + debug 日志的异常处理模式
- **依赖**: 2.4
- **验证**: 单元测试验证所有新字段被写入
- **预估**: 20min

### 2.6 前端 types 同步
- **目标**: api.ts 新增 log_id + trace_id 字段到 RetrieveResponse
- **文件**: `admin/src/types/api.ts`
- **依赖**: 2.2
- **验证**: TypeScript 编译通过
- **预估**: 10min

---

## Phase 3: 反馈 API (6 任务, ~2.5h)

### 3.1 错误码新增
- **目标**: ErrorCode 枚举添加 20020/20021/20022
- **文件**: `src/ragnexus/core/errors.py`
- **依赖**: 无
- **验证**: 导入可用
- **预估**: 10min

### 3.2 feedback schema
- **目标**: FeedbackRequest（trace_id必填/log_id建议/score 1~5/comment可选）+ FeedbackData（feedback_id/trace_id/log_id/score）
- **文件**: `src/ragnexus/schemas/feedback.py`
- **依赖**: 无
- **验证**: Pydantic 校验通过
- **预估**: 15min

### 3.3 feedback_service
- **目标**: 校验归属（查 retrieval_logs 验证 tenant 匹配 + trace_id 一致）→ Langfuse SDK create_score → 返回 feedback_id
- **文件**: `src/ragnexus/services/feedback_service.py`
- **要点**: 复用 get_langfuse_client()，不重复创建 client；score name="user_feedback"
- **依赖**: 1.5, 2.4, 3.1, 3.2
- **验证**: 单元测试 4 场景
- **预估**: 45min

### 3.4 feedback_router
- **目标**: POST /v1/rag/feedback，Depends(get_current_tenant)
- **文件**: `src/ragnexus/adapters/http/feedback_router.py`
- **依赖**: 3.3
- **验证**: curl 测试 4 场景
- **预估**: 30min

### 3.5 composition.py 注册
- **目标**: lifespan 中创建 feedback_router 并 include 到 app
- **文件**: `src/ragnexus/composition.py`
- **依赖**: 3.4
- **验证**: /openapi.json 显示新路由
- **预估**: 10min

### 3.6 单元测试
- **目标**: 覆盖 20020(Langfuse不可用)/20021(无权)/20022(越界)/正常提交 四场景
- **文件**: `tests/unit/services/test_feedback_service.py`, `tests/unit/adapters/test_feedback_router.py`
- **依赖**: 3.5
- **验证**: `pytest tests/unit/services/test_feedback_service.py -v` 全绿
- **预估**: 30min

---

## Phase 4: 前端反馈条 (4 任务, ~2h)

### 4.1 types/api.ts 新增类型
- **目标**: FeedbackRequest, FeedbackData 类型定义
- **文件**: `admin/src/types/api.ts`
- **依赖**: 3.2
- **验证**: TypeScript 编译
- **预估**: 10min

### 4.2 ragService.submitFeedback()
- **目标**: 封装 POST /v1/rag/feedback 调用
- **文件**: `admin/src/services/ragService.ts`
- **依赖**: 4.1
- **验证**: 函数签名正确
- **预估**: 15min

### 4.3 RetrievePage 反馈条组件
- **目标**: Card 内 chunk 列表上方添加五星反馈区（shadcn Card/Button/Textarea）
- **文件**: `admin/src/pages/RetrievePage.tsx`
- **要点**: 显示条件 trace_id 非空；无 trace_id 时隐藏 + 提示"Langfuse 未启用"
- **依赖**: 4.2, 2.6
- **验证**: 前端渲染正确
- **预估**: 60min

### 4.4 交互逻辑
- **目标**: 星级点击（已选及左侧黄色/未选灰色）、备注输入、提交（loading+成功"已评N分"+错误提示）、再次检索清空
- **文件**: `admin/src/pages/RetrievePage.tsx`
- **依赖**: 4.3
- **验证**: E2E 手动测试
- **预估**: 30min

---

## Phase 5: 离线测评脚本 (7 任务, ~2.5h)

### 5.1 eval 依赖
- **目标**: pyproject.toml optional-dependencies[eval] 新增 ragas>=0.2.0 + datasets>=2.0.0
- **文件**: `pyproject.toml`
- **依赖**: 无
- **验证**: `pip install -e ".[eval]"` 成功
- **预估**: 10min

### 5.2 eval 目录结构
- **目标**: 创建 eval/datasets/ + eval/reports/，.gitignore 加 eval/reports/
- **文件**: `eval/datasets/.gitkeep`, `eval/reports/.gitkeep`, `.gitignore`
- **依赖**: 无
- **验证**: 目录存在，git status 不追踪 reports
- **预估**: 5min

### 5.3 种子文档
- **目标**: 创建 data/ecommerce/ 目录 + 5~10 篇简短 Markdown 种子文档
- **文件**: `data/ecommerce/*.md`
- **要点**: 内容覆盖电商 FAQ（优惠券/退款/物流等），供 ground_truth 引用
- **依赖**: 无
- **验证**: 文件可读
- **预估**: 30min

### 5.4 种子测例
- **目标**: _seed_ecommerce.json，5~10 条手工 (question, ground_truth) 对
- **文件**: `eval/datasets/_seed_ecommerce.json`
- **要点**: 每条的 ground_truth 摘取自 5.3 的种子文档
- **依赖**: 5.3
- **验证**: JSON 格式合法
- **预估**: 20min

### 5.5 eval API Key
- **目标**: 用 create_api_key.py 创建 eval 专用 Key
- **命令**: `uv run python scripts/create_api_key.py --tenant-id eval_runner --name "评测专用"`
- **依赖**: 无（脚本已存在）
- **验证**: Key 可用，curl /v1/auth/me 返回 tenant_name=eval_runner
- **预估**: 10min

### 5.6 export 脚本
- **目标**: 从 Langfuse 拉 score ≤ threshold 的反馈 → 关联 trace → 输出 JSON
- **文件**: `scripts/export_eval_cases_from_langfuse.py`
- **要点**: argparse 5 参数（max-score/days/kb-id/output/merge），--merge 按 question 去重，httpx trust_env=False
- **依赖**: Phase 3（需 feedback 数据沉淀后才能测真实场景）
- **验证**: dry-run 成功，JSON 格式符合 golden set schema
- **预估**: 45min

### 5.7 eval 脚本
- **目标**: 读 golden set → 逐条调 POST retrieve → RAGAS 计算 context_precision + context_recall → 输出报告
- **文件**: `scripts/run_retrieval_eval.py`
- **要点**: argparse 5 参数（dataset/api-key/base-url/profile/output），context_recall 偏低单独列出，ground_truth 空则 skip
- **依赖**: 5.5（需要 API Key）
- **验证**: 对 _seed_ecommerce.json 跑一次，输出两项指标
- **预估**: 45min

---

## Phase 6: 文档与验收 (5 任务, ~1.5h)

### 6.1 tenant-onboarding 补充
- **目标**: 新增「检索反馈」小节
- **文件**: `docs/tenant-onboarding.md`
- **依赖**: Phase 3
- **验证**: 文档可读
- **预估**: 15min

### 6.2 README 离线测评
- **目标**: 新增三步流程说明（export → 补 ground_truth → run eval）
- **文件**: `README.md`
- **依赖**: Phase 5
- **验证**: 文档可读
- **预估**: 15min

### 6.3 E2E 可观测验收
- **目标**: 验证 LANGFUSE_ENABLED=true/false 场景 + Langfuse UI 可见 trace
- **命令**: curl retrieve + 浏览器 Langfuse UI
- **依赖**: Phase 2
- **验证**: 15 项验收标准逐条通过
- **预估**: 20min

### 6.4 反馈 API 验收
- **目标**: 正常/错误 log_id/score 越界/Langfuse 关闭 四场景
- **命令**: curl POST /v1/rag/feedback
- **依赖**: Phase 3
- **验证**: 4 场景均返回预期错误码
- **预估**: 15min

### 6.5 离线测评验收
- **目标**: export + 补 ground_truth + eval + 对比报告
- **命令**: python scripts/export_*.py → 编辑 JSON → python scripts/run_*.py
- **依赖**: Phase 5
- **验证**: 两张报告 JSON 数值可对比
- **预估**: 20min

---

## 依赖关系

```
Phase 1 (基础设施)
  ├── 1.0 Alembic ──────────────────────────────→ 2.4 migration
  ├── 1.1-1.4 docker+config+env+deps ───────────→ 1.5 client
  └── 1.5 client + 1.6 composition ─────────────→ 2.1 trace

Phase 2 (可观测)
  ├── 2.1 trace + 2.2 log_id ───────────────────→ 2.3/2.6 schema+前端
  └── 2.4 migration + 2.5 repo ──────────────────→ 3.3 feedback_service

Phase 3 (反馈) ──────────────────────────────────→ Phase 4 (前端) + Phase 5.6 export

Phase 5 (脚本) 可部分并行于 Phase 3-4
Phase 6 (文档验收) 依赖 Phase 1-5 全部完成
```

## 风险清单

| 风险 | 影响 | 缓解 |
|---|---|---|
| Alembic 未初始化 | 2.4 阻塞 | 1.0 前置检查 |
| Langfuse SDK API 变更 | 1.5 重写 | 锁定版本 >=2.0.0,<3.0.0 |
| 前端 shadcn 组件不兼容 | Phase 4 返工 | 先用现有组件验证 |
| RAGAS API 变更 | 5.7 重写 | 锁定 ragas>=0.2.0 |

## 预估总工作量

| Phase | 任务 | 预估 |
|---|---|---|
| Phase 1 | 7 | 2h |
| Phase 2 | 6 | 3h |
| Phase 3 | 6 | 2.5h |
| Phase 4 | 4 | 2h |
| Phase 5 | 7 | 2.5h |
| Phase 6 | 5 | 1.5h |
| **总计** | **35** | **~13.5h** |
