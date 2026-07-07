# Task 2.1: retrieve_router.py 包裹 Langfuse trace

## Task Requirements

从 plan 提取: retrieve_router.py 中 retrieve() 函数用 Langfuse trace 包裹全过程

## 设计要点

### trace 结构
```
trace "rag_retrieve"
├── span "query_processing"  (input: search_query, metadata: tenant_id/profile)
├── span "retrieval"         (input: effective_query, output: chunk_id+score 摘要)
└── span "rerank"            (input: chunk_count_before, output: chunk_count_after+score)
```

### metadata
- trace metadata: tenant_id, kb_ids, profile, plan, effective_query
- 每个 span 的 input 记录该阶段的 raw input

### output 约束
- retrieval span output 只存 chunk_id + score 摘要（不存完整文本，避免 token 浪费）
- rerank span output 存 rerank 前后数量和分数变化

### 关键行为
- LANGFUSE_ENABLED=false 时 trace 为 None，所有 span 创建跳过
- trace 创建失败不影响业务（返回值保留 log_id + trace_id 字段）
- 从 RetrieveUseCase 返回结果中提取各阶段数据构建 span

## Acceptance
- `LANGFUSE_ENABLED=true` + 启动 langfuse → UI 可见 trace "rag_retrieve" + 3 spans
- `LANGFUSE_ENABLED=false` → 正常检索，无 Langfuse 错误日志

## 依赖
- 1.6 (composition.py 注入 langfuse_client)
- retrieve_router.py 通过 DI 获取 RetrieveObservability 实例
