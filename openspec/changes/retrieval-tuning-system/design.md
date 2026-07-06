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

| 目录 | 说明 |
|---|---|
| `data/ecommerce/` | 种子文档 |
| `eval/datasets/` | golden set JSON |
| `eval/reports/` | 评测报告（.gitignore） |

### 9. docker-compose 关键配置

```yaml
langfuse:
  environment:
    NEXTAUTH_URL: http://localhost:3000
    NEXTAUTH_SECRET: changeme_replace_in_production  # B2 修复
    ENCRYPTION_KEY: changeme_replace_in_production
```

### 10. 边界行为

- LANGFUSE_ENABLED=true 但 Langfuse 不可达 → trace 创建静默失败(warning)，不抛异常
- LANGFUSE_ENABLED=true 但 PUBLIC_KEY 为空 → 同静默失败
- LANGFUSE_ENABLED=false → trace_id=null，log_id 仍可用
- feedback 失败 → 返回对应错误码，retrieve 不受影响
