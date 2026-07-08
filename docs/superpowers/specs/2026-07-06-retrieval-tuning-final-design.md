# 检索效果调优系统 — 最终设计总览

> 10 项决策已确认，以下为完整技术方案

---

## 决策汇总

| # | 决策项 | 结论 |
|---|---|---|
| 1 | Langfuse compose | 直接加到现有 docker-compose.yml |
| 2 | retrieval_logs 迁移 | Alembic migration + schema.sql 双写 |
| 3 | 前端反馈条 | Admin 调试台检索结果区 |
| 4 | langfuse-db 持久化 | 加 named volume `langfusedata` |
| 5 | trace 策略 | 全量写入，失败不影响主链路 |
| 6 | Langfuse SDK | 官方 Python SDK (langfuse>=2.0.0) |
| 7 | trace 埋点层 | retrieve_router 层（包裹 execute） |
| 8 | feedback 鉴权 | 复用现有 Bearer Token |
| 9 | Admin Key | 复用 admin/.env API_KEY |
| 10 | eval base URL | 读 .env HOST:PORT 构建 |

---

## 架构总图

```
                          ┌─────────────────────────────────────────┐
                          │           RAGNexus 中台                  │
  业务方 ──API Key──→     │                                         │
                          │  retrieve_router (NEW: 包裹trace)        │
  调试台 ──API Key──→     │    ├─ plan解析 → profile展开 → 限流     │
                          │    ├─ [trace开始] langfuse_client        │
                          │    ├─ RetrieveUseCase.execute()          │
                          │    │   ├─ [span] query_processing        │
                          │    │   ├─ [span] retrieval               │
                          │    │   └─ [span] rerank                  │
                          │    ├─ [trace结束] flush (fire-and-forget)│
                          │    ├─ INSERT retrieval_logs (NEW 4字段)  │
                          │    └─ 返回 {chunks, log_id, trace_id}    │
                          │                                         │
                          │  feedback_router (NEW)                   │
                          │    ├─ 校验 tenant + log_id + trace_id    │
                          │    ├─ Langfuse SDK create_score()        │
                          │    └─ 返回 {feedback_id}                 │
                          └──────────┬───────────────────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                      ▼
     ┌────────────────┐   ┌──────────────────┐   ┌──────────────────┐
     │   Langfuse      │   │  离线测评 (NEW)   │   │  现有基础设施     │
     │   :3000         │   │                  │   │                  │
     │                 │   │ export脚本        │   │ PostgreSQL:15432 │
     │ Trace面板       │←──│  ← 拉score≤3     │   │ ES:9200          │
     │ Score反馈       │   │  → JSON候选      │   │ Redis:6379       │
     │                 │   │                  │   │                  │
     │ langfuse-db     │   │ eval脚本          │   │                  │
     │ (独立Postgres)  │   │  ← 读golden set  │   │                  │
     └────────────────┘   │  → HTTP调retrieve│   │                  │
                           │  → RAGAS计算     │   │                  │
                           │  → JSON报告      │   │                  │
                           └──────────────────┘   └──────────────────┘
```

---

## 新增/修改文件清单

### 新增 (7文件)

| 路径 | 说明 |
|---|---|
| `src/ragnexus/observability/__init__.py` | 模块入口 |
| `src/ragnexus/observability/langfuse_client.py` | Langfuse SDK 封装，RetrieveObservability |
| `src/ragnexus/schemas/feedback.py` | FeedbackRequest, FeedbackData |
| `src/ragnexus/services/feedback_service.py` | 反馈业务逻辑 |
| `src/ragnexus/adapters/http/feedback_router.py` | POST /v1/rag/feedback |
| `scripts/export_eval_cases_from_langfuse.py` | 导出低分case |
| `scripts/run_retrieval_eval.py` | RAGAS批量评测 |

### 修改 (14文件)

| 路径 | 改动 |
|---|---|
| `docker-compose.yml` | +langfuse +langfuse-db services |
| `config.py` | +4个 LANGFUSE_* 字段 |
| `.env` / `.env.example` | +LANGFUSE_*变量 |
| `pyproject.toml` | +langfuse依赖, +eval optional-deps |
| `core/errors.py` | +20020/20021/20022 |
| `composition.py` | 注入新模块, 注册新路由 |
| `retrieve_router.py` | 包裹trace, 响应+log_id/trace_id |
| `application/retrieve_use_case.py` | 可选: 不改, trace在router层 |
| `adapters/retrieve_log/pg.py` | +4字段写入 |
| `docs/sql/schema.sql` | retrieval_logs扩展 |
| `frontend/src/types/api.ts` | +log_id, trace_id, feedback类型 |
| `frontend/.../RetrievePage` | +反馈条组件 |
| `admin/src/utils/ragService.ts` | +submitFeedback() |
| `.gitignore` | +eval/reports/ |

---

## Trace 结构定义

```python
# trace: "rag_retrieve"
metadata = {
    "tenant_id": "my_tenant",
    "kb_id": ["939a5baf-xxxx"],
    "user_id": "admin",
    "profile": "balanced",
    "plan": "standard",
}

# span 1: "query_processing"
input = {"raw_query": "满减和优惠券能叠加吗"}
output = {
    "effective_query": "优惠券和满减活动能否同时使用",  # LLM改写后
    "synonym_applied": True,                            # 词表扩展
}

# span 2: "retrieval"
input = {"mode": "hybrid", "search_query": "优惠券 满减 叠加 同时使用"}
output = {
    "vector_count": 20,
    "bm25_count": 20,
    "fused_count": 35,       # RRF去重后
    "hybrid_degraded": False,
}

# span 3: "rerank"
input = {"enabled": True, "candidates": 20}
output = {
    "reranked_count": 20,
    "degraded": False,
}

# trace output (不塞全文, 只存摘要)
output = {
    "chunks": [
        {"id": "doc1_chunk3", "score": 0.92},
        {"id": "doc2_chunk1", "score": 0.87},
        ...
    ]
}
```

---

## retrieval_logs 表扩展

```sql
ALTER TABLE retrieval_logs
  ADD COLUMN trace_id        VARCHAR(64),   -- Langfuse trace标识
  ADD COLUMN profile         VARCHAR(32),   -- 检索策略(speed/balanced/quality/custom)
  ADD COLUMN search_query    TEXT,          -- 送入搜索引擎的query(词表扩展后)
  ADD COLUMN effective_query TEXT;          -- LLM改写后的query
```

---

## 配置新增

```bash
# .env
LANGFUSE_ENABLED=false
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

---

## docker-compose 新增

```yaml
langfuse-db:
  image: postgres:16-alpine
  environment:
    POSTGRES_USER: langfuse
    POSTGRES_PASSWORD: langfuse
    POSTGRES_DB: langfuse
  volumes:
    - langfusedata:/var/lib/postgresql/data
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U langfuse -d langfuse"]
    interval: 2s
    timeout: 3s
    retries: 30

langfuse:
  image: langfuse/langfuse:2
  ports:
    - "3000:3000"
  environment:
    DATABASE_URL: postgresql://langfuse:langfuse@langfuse-db:5432/langfuse
    NEXTAUTH_URL: http://localhost:3000
    NEXTAUTH_SECRET: changeme_please_replace_in_production
    ENCRYPTION_KEY: changeme_please_replace_in_production
  depends_on:
    langfuse-db:
      condition: service_healthy

volumes:
  langfusedata:   # NEW
```

---

## 错误码新增

| code | HTTP | 消息 | 触发 |
|---|---|---|---|
| 20020 | 503 | 反馈服务不可用 | LANGFUSE_ENABLED=false 或写入异常 |
| 20021 | 403 | 无权操作该反馈记录 | log_id/trace_id 不匹配或跨租户 |
| 20022 | 422 | 评分超出允许范围(1-5) | score < 1 或 > 5 |

---

## 与现有套餐系统的关系

- **零新增限制**: 可观测和反馈是基础设施，不消耗租户配额
- **零新表**: feedback 不建本地表，Langfuse 是唯一真相源
- **零新依赖注入复杂度**: langfuse_client 作为单例注入 composition
- **LANGFUSE_ENABLED=false**: 整个可观测层静默，行为与当前完全一致
