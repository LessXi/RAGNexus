# 检索效果调优 — 需求全景图解

> 三篇飞书文档需求 + 现有 RAGNexus 架构，从第一性原理出发

---

## 一、三角闭环全景

```mermaid
graph TB
    subgraph core["🔵 RAGNexus 中台（不变）"]
        direction LR
        API["POST /v1/rag:retrieve"]
        Pipeline["查询改写 → 双路召回 → RRF融合 → 重排"]
        API --> Pipeline
    end

    subgraph new1["🟢 可观测（NEW）"]
        LF["Langfuse"]
        Trace["每次检索 → 一条 trace
3个子span记录全过程"]
        LF --> Trace
    end

    subgraph new2["🟠 可反馈（NEW）"]
        Feedback["POST /v1/rag/feedback"]
        Star["1~5分 + 备注
锚定 trace_id"]
        Feedback --> Star
    end

    subgraph new3["🟣 离线测评（NEW）"]
        Export["export脚本
从Langfuse拉低分case"]
        Eval["eval脚本
RAGAS批量跑分"]
        Golden["golden set
人工补ground_truth"]
        Export --> Golden --> Eval
    end

    core -->|"旁路写入 trace
(fire-and-forget)"| new1
    new1 -->|"反馈挂到trace上"| new2
    new1 -->|"低分记录→候选测例"| new3
    new3 -->|"发现系统性问题
→改词表/改profile"| core

    style core fill:#e3f2fd,stroke:#1565c0
    style new1 fill:#e8f5e9,stroke:#2e7d32
    style new2 fill:#fff3e0,stroke:#ef6c00
    style new3 fill:#f3e5f5,stroke:#7b1fa2
```

> **闭环逻辑**：可观测记录现场 → 反馈收集评分 → 离线测评量化效果 → 改配置 → 再测 → 上线 → 再看可观测数据

---

## 二、新增组件与现有架构的关系

```mermaid
graph TB
    subgraph docker["docker-compose 新增 2 个 service"]
        LFDB["langfuse-db
独立 Postgres
库名: langfuse"]
        LFSRV["langfuse
镜像 langfuse/langfuse:2
端口 :3000"]
        LFSRV --> LFDB
    end

    subgraph existing["现有服务（不变）"]
        DB["db: pgvector/pg16
库名: ragnexus"]
        ES["elasticsearch:8.17"]
        Redis["redis:7"]
        App["app: FastAPI :8000"]
        Worker["worker: Celery"]
    end

    subgraph newcode["新增代码模块"]
        Obs["observability/
langfuse_client.py
RetrieveObservability"]
        FbSvc["services/
feedback_service.py"]
        FbRouter["adapters/http/
feedback_router.py
POST /v1/rag/feedback"]
        EvScripts["scripts/
export_eval_cases.py
run_retrieval_eval.py"]
    end

    subgraph newdata["新增数据"]
        RL["retrieval_logs 扩展
+4 列: trace_id,
profile, search_query,
effective_query"]
        EvalData["eval/datasets/
+ _seed_ecommerce.json
+ ecommerce_retrieval.json"]
        DataDir["data/ecommerce/
种子文档（新建）"]
    end

    App -->|"httpx POST
fire-and-forget"| LFSRV
    App --> Obs
    App --> FbRouter
    FbRouter --> FbSvc --> LFSRV
    App --> RL
    EvScripts -->|"调 API"| App
    EvScripts -->|"拉低分case"| LFSRV
    EvScripts --> EvalData
    EvalData --> DataDir

    style docker fill:#fff3e0,stroke:#ef6c00
    style existing fill:#e3f2fd,stroke:#1565c0
    style newcode fill:#e8f5e9,stroke:#2e7d32
    style newdata fill:#f3e5f5,stroke:#7b1fa2
```

---

## 三、一次检索的完整生命周期（核心链路）

```mermaid
sequenceDiagram
    autonumber
    participant B as 🏢 业务方
    participant R as 📡 retrieve_router
    participant UC as ⚙️ RetrieveUseCase
    participant Obs as 🔍 Langfuse Client
    participant PG as 🗄️ retrieval_logs
    participant LF as 📊 Langfuse Server

    rect rgb(227,242,253)
        Note over B,LF: Phase 1: 请求接入（不变）
        B->>R: POST /v1/rag:retrieve<br/>{query, kb_ids, profile}
        R->>R: plan解析 + profile展开 + 限流
        Note right of R: tenant_id 来自 API Key
    end

    rect rgb(232,245,233)
        Note over B,LF: Phase 2: 开启 Trace（NEW）
        R->>Obs: 创建 trace "rag_retrieve"
        Note over Obs: metadata = {<br/>  tenant_id, kb_ids,<br/>  profile, plan<br/>}
        Obs-->>LF: 异步写入
    end

    rect rgb(227,242,253)
        Note over B,LF: Phase 3: 检索管道（不变）
        R->>UC: execute(query, kb_ids, ...)
        
        UC->>Obs: span: query_processing
        Note over UC: 原始query → LLM改写<br/>→ 词表扩展
        UC->>Obs: span end

        UC->>Obs: span: retrieval
        Note over UC: mode, vector命中数<br/>bm25命中数, 是否降级
        UC->>Obs: span end

        UC->>Obs: span: rerank
        Note over UC: 启用? 候选数? 降级?
        UC->>Obs: span end

        UC-->>R: RetrieveResult
    end

    rect rgb(255,243,224)
        Note over B,LF: Phase 4: 落库（NEW 扩展）
        R->>PG: INSERT retrieval_logs
        Note over PG: +trace_id, profile<br/>+search_query<br/>+effective_query
        PG-->>R: log_id = BIGSERIAL
    end

    rect rgb(232,245,233)
        Note over B,LF: Phase 5: 响应返回（NEW 字段）
        R->>Obs: flush trace (fire-and-forget)
        R-->>B: {chunks, log_id, trace_id}
        Note over B: log_id → 业务方关联流水<br/>trace_id → 研发在Langfuse看详情
    end
```

---

## 四、Trace 内部结构

```mermaid
graph TB
    Trace["🔷 trace: rag_retrieve"]
    
    Meta["📋 metadata"]
    Meta --> M1["tenant_id: 'my_tenant'"]
    Meta --> M2["kb_ids: ['939a5baf-...']"]
    Meta --> M3["profile: 'balanced'"]
    Meta --> M4["plan: 'standard'"]

    S1["📗 span: query_processing"]
    S1 --> S1i["input: {raw_query}"]
    S1 --> S1o["output: {effective_query, synonym_applied}"]

    S2["📘 span: retrieval"]
    S2 --> S2i["input: {mode, search_query}"]
    S2 --> S2o["output: {vector_count, bm25_count, fused_count, degraded}"]

    S3["📙 span: rerank"]
    S3 --> S3i["input: {enabled, candidates}"]
    S3 --> S3o["output: {reranked_count, degraded}"]

    TO["📤 trace output"]
    TO --> TO1["[{chunk_id, score}, ...]"]
    Note1["⚠️ 不塞全文，只存摘要<br/>避免面板体积爆炸"]

    Trace --> Meta
    Trace --> S1
    Trace --> S2
    Trace --> S3
    Trace --> TO
    S1 -.-> Note1
    S2 -.-> Note1
    S3 -.-> Note1

    style Trace fill:#bbdefb,stroke:#1565c0,stroke-width:3px
    style Meta fill:#e3f2fd,stroke:#1565c0
    style S1 fill:#c8e6c9,stroke:#2e7d32
    style S2 fill:#c8e6c9,stroke:#2e7d32
    style S3 fill:#c8e6c9,stroke:#2e7d32
    style TO fill:#fff9c4,stroke:#f9a825
    style Note1 fill:#ffcdd2,stroke:#c62828
```

---

## 五、反馈链路

```mermaid
sequenceDiagram
    autonumber
    participant Admin as 🖥️ Admin调试台
    participant API as 📡 POST /v1/rag/feedback
    participant PG as 🗄️ retrieval_logs
    participant LF as 📊 Langfuse
    participant Tenant as 🔑 当前租户

    rect rgb(232,245,233)
        Note over Admin,Tenant: 前置条件：本次检索成功，trace_id 非空
        Admin->>Admin: 用户点选 3 星 + 输入备注
        Note over Admin: ★★★☆☆  "排第三的chunk才是对的"
    end

    rect rgb(227,242,253)
        Note over Admin,Tenant: Step 1: 提交反馈
        Admin->>API: POST /v1/rag/feedback<br/>{trace_id, log_id, score:3, comment}
        Note over API: Auth: Bearer API Key<br/>→ TenantContext
    end

    rect rgb(255,243,224)
        Note over Admin,Tenant: Step 2: 校验归属
        API->>PG: SELECT WHERE id=log_id
        PG-->>API: {tenant_id, trace_id}
        
        alt log_id 不存在 或 租户不匹配
            API-->>Admin: ❌ 20021 无权操作
        else score ∉ [1,5]
            API-->>Admin: ❌ 20022 超出范围
        end
    end

    rect rgb(232,245,233)
        Note over Admin,Tenant: Step 3: 写入 Langfuse
        API->>LF: create_score(trace_id,<br/>name="user_feedback",<br/>value=3, comment=...)
        
        alt Langfuse 不可用
            API-->>Admin: ❌ 20020 反馈服务不可用
        else 写入成功
            LF-->>API: feedback_id
            API-->>Admin: ✅ 已提交（已评 3 分）
            Note over Admin: 星星变黄，显示"已评3分"
        end
    end
```

---

## 六、离线测评流水线

```mermaid
graph LR
    subgraph step1["Step 1: 导出候选"]
        LF["📊 Langfuse
低分反馈"] -->|"export脚本
筛选 score ≤ 3"| Imported["📄 imported_from_feedback.json
question✅ source✅
ground_truth❌ 留空"]
    end

    subgraph step2["Step 2: 人工标注"]
        Imported -->|"人工从知识库摘取关键句
填写 ground_truth"| Main["📄 ecommerce_retrieval.json
question✅ ground_truth✅
+ 种子测例 ✅"]
        Seed["📄 _seed_ecommerce.json
5~10条手工种子"] -.->|"冷启动"| Main
    end

    subgraph step3["Step 3: 批量评测"]
        Main -->|"run_retrieval_eval
逐条调 POST retrieve
user_id 通过租户区分"| RAGAS["🧮 RAGAS 计算"]
        RAGAS --> CP["context_precision
精准度"]
        RAGAS --> CR["context_recall
召回率"]
    end

    subgraph step4["Step 4: 对比分析"]
        CP --> Report["📊 eval/reports/profile_balanced.json"]
        CR --> Report
        Report --> Compare["改词表前 vs 改词表后
改profile前 vs 改profile后<br/>→ 数值说话"]
    end

    style step1 fill:#fff3e0,stroke:#ef6c00
    style step2 fill:#f3e5f5,stroke:#7b1fa2
    style step3 fill:#e8f5e9,stroke:#2e7d32
    style step4 fill:#e3f2fd,stroke:#1565c0
```

---

## 七、文件变更全景

```mermaid
graph TB
    subgraph add["➕ 新增 7 文件"]
        A1["observability/__init__.py"]
        A2["observability/langfuse_client.py<br/>RetrieveObservability"]
        A3["schemas/feedback.py<br/>FeedbackRequest/FeedbackData"]
        A4["services/feedback_service.py"]
        A5["adapters/http/feedback_router.py<br/>POST /v1/rag/feedback"]
        A6["scripts/export_eval_cases_from_langfuse.py"]
        A7["scripts/run_retrieval_eval.py"]
    end

    subgraph mod["✏️ 修改 14 文件"]
        M1["docker-compose.yml<br/>+langfuse +langfuse-db"]
        M2["config.py<br/>+4 LANGFUSE_* 字段"]
        M3[".env / .env.example"]
        M4["pyproject.toml<br/>+langfuse +eval deps"]
        M5["core/errors.py<br/>+20020/20021/20022"]
        M6["composition.py<br/>注入新模块"]
        M7["retrieve_router.py<br/>包裹trace +响应字段"]
        M8["adapters/retrieve_log/pg.py<br/>+4字段写入"]
        M9["docs/sql/schema.sql<br/>retrieval_logs扩展"]
        M10["Alembic 0006 migration"]
        M11["frontend types/api.ts<br/>+log_id/trace_id/feedback"]
        M12["frontend RetrievePage<br/>+五星反馈条"]
        M13["frontend ragService.ts<br/>+submitFeedback()"]
        M14[".gitignore<br/>+eval/reports/"]
    end

    subgraph newdata["📁 新建目录/文件"]
        D1["data/ecommerce/<br/>种子文档"]
        D2["eval/datasets/<br/>_seed_ecommerce.json"]
        D3["eval/reports/<br/>评测报告（gitignore）"]
    end

    style add fill:#e8f5e9,stroke:#2e7d32
    style mod fill:#fff3e0,stroke:#ef6c00
    style newdata fill:#f3e5f5,stroke:#7b1fa2
```

---

## 八、错误码总览（现有 + 新增）

| code | HTTP | 含义 | 来源 |
|---|---|---|---|
| 20005 | 429 | API 限流 | 现有 |
| 20013 | 403 | 套餐不支持 | 现有 |
| 20014 | 429 | 配额超限 | 现有 |
| **20020** | 503 | 反馈服务不可用 | **NEW** |
| **20021** | 403 | 无权操作该反馈 | **NEW** |
| **20022** | 422 | 评分超出范围 | **NEW** |

---

## 九、关键边界（不做什么）

| 不做 | 原因 |
|---|---|
| 不建 feedbacks 表 | Langfuse 是反馈唯一真相源 |
| 不做历史查询 API | 查历史直接用 Langfuse UI |
| 不做 Langfuse 统计大盘 | 非本文范围 |
| 不做 RAGAS 前端页面 | 脚本独立运行 |
| faithfulness / answer_relevancy | rag-center 只返回 chunk，不生成答案 |
| 不替换 retrieve 接口 | Langfuse 是旁路，契约不变 |
| 不接入 LangSmith | 云端托管，数据安全风险 |

---

## 十、验收标准速查

| # | 标准 | 验收方式 |
|---|---|---|
| 1 | LANGFUSE_ENABLED=true → log_id + trace_id 非空 | curl retrieve |
| 2 | Langfuse UI 可见 trace + 3个span + metadata | 浏览器打开 :3000 |
| 3 | LANGFUSE_ENABLED=false → trace_id=null, log_id 正常 | curl retrieve |
| 4 | retrieval_logs 4新字段有值，id=log_id | 查 DB |
| 5 | 调试台 4星+备注 → Langfuse Scores=4 | Admin UI → Langfuse UI |
| 6 | curl feedback score=2 → Langfuse user_feedback=2 | curl + Langfuse UI |
| 7 | 错误 log_id → 20021 | curl |
| 8 | score=0/6 → 20022 | curl |
| 9 | LANGFUSE_ENABLED=false → feedback 20020 | curl |
| 10 | 再次检索 → 反馈条清空 | Admin UI |
| 11 | export 拉出 score≤3 的 case，ground_truth 空 | 跑脚本 |
| 12 | 补 ground_truth 后 eval 输出 2 项指标 | 跑脚本 |
| 13 | ground_truth 空的 case 自动 skip | 终端输出 |
| 14 | 改配置前后指标可对比 | diff 两份报告 |
| 15 | 缺 key/DB 挂/Langfuse 挂 → 友好报错不崩溃 | 故障注入 |
