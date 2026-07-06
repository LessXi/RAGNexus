---
comet_change: retrieval-tuning-system
role: technical-design
canonical_spec: openspec
---

# 检索效果调优系统 — 技术设计

## 1. 概述

为 RAGNexus 建立检索效果调优三角闭环：可观测（Langfuse trace）→ 可反馈（Feedback API）→ 离线测评（RAGAS 脚本）。

## 2. 架构概览

```
RAGNexus 中台（不变）
├── retrieve_router ──→ [NEW] Langfuse trace (fire-and-forget)
├── retrieve_router ──→ [NEW] 响应含 log_id + trace_id
├── [NEW] feedback_router ──→ Langfuse score
└── [NEW] eval 脚本 ──→ HTTP 调 retrieve → RAGAS 计算
```

Langfuse 是旁路辅助，不替换核心接口。`LANGFUSE_ENABLED=false` 时整个可观测层静默。

## 3. 核心设计

### 3.1 Trace 结构

```
trace: "rag_retrieve"
metadata: {tenant_id, kb_ids, profile, plan}
├── span: query_processing → {raw_query, effective_query, synonym_applied}
├── span: retrieval → {mode, vector_count, bm25_count, fused_count, degraded}
└── span: rerank → {enabled, candidates, reranked_count, degraded}
output: [{chunk_id, score}, ...]  # 只存摘要
```

### 3.2 双链 ID

| ID | 来源 | 生成方式 | 用途 | 何时为 null |
|---|---|---|---|---|
| log_id | nanoid 本地预生成 | `"log_" + nanoid(12)`，纯内存 0ms | 业务方关联流水 | 永不 |
| trace_id | Langfuse SDK 生成 | trace 创建时返回 | 研发面板定位 | LANGFUSE_ENABLED=false |

`retrieval_logs` 表新增 `log_id VARCHAR(24) UNIQUE` 列（与 PK `id` 分离），旧数据 NULL。log_id 的本质是"响应时刻就能确定的唯一标识"，不应依赖 DB 的 BIGSERIAL。

### 3.3 反馈链路

```
POST /v1/rag/feedback {trace_id, log_id, score:1~5, comment?}
  → 鉴权: TenantContext (Bearer Token)
  → 校验: 查 retrieval_logs 确认租户归属 (如有 log_id)
  → 写入: Langfuse SDK create_score(name="user_feedback")
  → 错误码: 20020(不可用) / 20021(无权) / 20022(越界)
```

### 3.4 离线测评

两个独立脚本，不嵌 FastAPI：

| 脚本 | 功能 | 输入 | 输出 |
|---|---|---|---|
| export_eval_cases | 从 Langfuse 拉低分反馈 | LANGFUSE_* env | JSON (ground_truth 留空) |
| run_retrieval_eval | RAGAS 批量评测 | golden set JSON | context_precision + context_recall |

## 4. 模块分解

### 新增 Python 模块

| 模块 | 职责 |
|---|---|
| `observability/langfuse_client.py` | SDK 封装，RetrieveObservability，LANGFUSE_ENABLED 开关 |
| `schemas/feedback.py` | FeedbackRequest, FeedbackData |
| `services/feedback_service.py` | 校验归属 + Langfuse score 写入 |
| `adapters/http/feedback_router.py` | POST /v1/rag/feedback |

### 修改现有模块

| 模块 | 改动 |
|---|---|
| `retrieve_router.py` | 包裹 trace，响应加 log_id/trace_id |
| `retrieve_use_case.py` | 不透传 trace（在 router 层包裹） |
| `retrieve_log/pg.py` | 写入 4 个新字段 |
| `config.py` | +4 LANGFUSE_* 配置项 |
| `core/errors.py` | +3 错误码 |
| `composition.py` | 注入新模块 |
| `docker-compose.yml` | +2 service |
| `schema.sql` | retrieval_logs 扩展 |

## 5. 数据模型

### retrieval_logs 扩展

```sql
ALTER TABLE retrieval_logs
  ADD COLUMN log_id          VARCHAR(24) UNIQUE,  -- nanoid 外部标识
  ADD COLUMN tenant_id       TEXT,                -- 检索所属租户，feedback 校验用
  ADD COLUMN trace_id        VARCHAR(64),         -- Langfuse trace 标识
  ADD COLUMN profile         VARCHAR(32),         -- 检索策略
  ADD COLUMN search_query    TEXT,                -- 送入搜索引擎的 query
  ADD COLUMN effective_query TEXT;                -- LLM 改写后的 query
```
新列均可空，不影响旧数据。通过 Alembic migration `0008_retrieval_log_observability` 执行。

**log_id 设计原理**：使用 `"log_" + nanoid(12)` 在请求进入时本地预生成，不依赖 DB 自增，保持 fire-and-forget 日志模式。

## 6. 配置

```bash
LANGFUSE_ENABLED=false
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

docker-compose langfuse service 须配置 `NEXTAUTH_SECRET` 和 `ENCRYPTION_KEY`。

## 7. 错误码

| code | HTTP | 消息 |
|---|---|---|
| 20020 | 503 | 反馈服务不可用 |
| 20021 | 403 | 无权操作该反馈记录 |
| 20022 | 422 | 评分超出允许范围(1-5) |

## 8. 边界行为

| 场景 | 行为 |
|---|---|
| LANGFUSE_ENABLED=false | trace_id=null，log_id 正常，可观测层静默 |
| LANGFUSE_ENABLED=true 但 Langfuse 不可达 | trace 创建静默失败(warning)，检索正常 |
| LANGFUSE_ENABLED=true 但 PUBLIC_KEY 为空 | 同上 |
| feedback 提交时 Langfuse 不可用 | 返回 20020，retrieve 不受影响 |
| feedback 提交时 log_id 不匹配 | 返回 20021 |
| feedback 提交时 score 越界 | 返回 20022 |

## 9. 非目标

- 不建 feedbacks 表（Langfuse 持久化）
- 不做历史查询 API（用 Langfuse UI）
- 不做 Langfuse 统计大盘
- 不做 RAGAS 前端页面（脚本独立）
- faithfulness/answer_relevancy 不在范围（只返回 chunk）
- 不替换 retrieve 接口契约
