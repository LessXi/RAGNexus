## Context

RAGNexus 当前是纯向量检索链路（embed → pgvector search → return）。第一期骨架已稳定运行，HTTP 契约已固化：`POST /v1/rag:retrieve`，请求体包含 `query`、`kb_ids`、`top_k`，响应返回 `SearchHit[]`。

本期引入两个 LLM 后台优化：

- **Rerank**（重排）：向量召回后、返回前，用 LLM 对候选 chunk 做语义相关性打分排序
- **Query Rewrite**（查询改写）：embedding 前，用 LLM 判断并改写口语化/模糊 query

两者都是对调用方完全透明的后台优化，HTTP 契约零变化。

## Goals / Non-Goals

**Goals:**
- 引入通用 LLM 调用基础设施（`LLMProvider`），被 rerank/rewrite 共享
- 实现 LLM 重排：向量召回后对候选 chunk 做相关性重排
- 实现查询改写：embedding 前改写口语化/模糊 query
- 缓存机制：向量相似匹配（cosine ≥ 0.95），降低重复 query 的 LLM 调用
- KB 写入时主动清空缓存
- 降级安全：LLM 不可用时自动回退原始排序/原始 query
- 全部通过 `.env` 独立开关控制，默认禁用

**Non-Goals:**
- HTTP 请求/响应 schema 变更
- `SearchHit` 字段追加（`score` 始终为向量原始分）
- 新依赖引入（httpx/asyncio/json/re 均已存在）
- 错误码新增（复用 `MODEL_ERROR(40000)~MODEL_RATE_LIMIT(40005)`）
- 多 query 变体改写（推后续）

### 禁止修改

以下文件/模块必须保持完全不变，任何实现不得触碰：
- `src/ragnexus/adapters/http/retrieve_router.py`（请求/响应 schema 零变化）
- `src/ragnexus/domain/models.py`（`SearchHit` 不加字段、不改语义）
- `src/ragnexus/core/errors.py`（不新增错误码，复用 `MODEL_ERROR(40000)~MODEL_RATE_LIMIT(40005)`）
- 现有 5 个 Port 签名（`EmbedderPort`、`VectorStorePort`、`ChunkerPort`、`DocumentRepositoryPort`、`LoggerPort`）
- `retrieve_logs` 表 schema

## 架构

### 模块拆分

```
┌─────────────────────────────────────────────────┐
│                  RetrieveUseCase                  │
│  (注入 Rewriter + Reranker, 串联 rewrite→embed→  │
│   search→rerank→return)                          │
└──────────┬────────────────────┬─────────────────┘
           │                    │
           ▼                    ▼
┌──────────────────┐  ┌──────────────────┐
│  RewritePort     │  │  RerankPort      │  ← domain/ports.py (Protocol)
│  LLMRewriteProvider│  │  LLMRerankProvider│  ← adapters/ 实现
│  NoopRewriteProvider│  │  NoopRerankProvider│  ← 禁用时直通
└────────┬─────────┘  └────────┬─────────┘
         │                     │
         └─────────┬───────────┘
                   ▼
        ┌────────────────────┐
        │   LLMProvider      │  ← adapters/llm/ (ABC, 不是 domain port)
        │   OpenAICompatible │     共享基础设施，不单独拆 cap spec
        └────────────────────┘
```

**为什么 LLMProvider 不是一个独立的 capability spec**：
LLMProvider 是纯基础设施抽象（HTTP client + 重试 + 并发控制），没有业务需求/验收场景。它的"需求"完全由两个上层能力（rerank/rewrite）的调用协议定义。拆成独立 cap spec 会产生空需求文档，增加维护负担。

### 数据流

```
原始 query → Rewrite → 改写 query → Embed → Vector Search (candidate_k) → Rerank → 返回 top_k
                                                                    ↑ 缓存 lookup
                                          ↑ 缓存 lookup             KB 写入清空缓存
```

## Decisions

### D1: LLMProvider 用 ABC 而非 Protocol
- **决策**：`LLMProvider` 用 `abc.ABC`，定义在 `adapters/llm/base.py`
- **理由**：包含共享状态（HTTP client、semaphore、重试配置），不适合 `typing.Protocol`（纯接口契约）
- **替代方案**：用 Protocol + mixin — 复杂度与收益不匹配

### D2: RerankPort / RewritePort 用 Protocol
- **决策**：两者在 `domain/ports.py` 中以 `typing.Protocol` 定义
- **理由**：与现有 5 个 Port 风格一致，domain 层不依赖实现

### D3: 降级策略 — 内部消化
- **决策**：LLM 调用失败时，LLMRerankProvider 内部 catch 异常，返回原始排序
- **理由**：不向 use case 传播错误；不中断接口

### D4: 缓存策略 — 向量相似匹配
- **决策**：自建 dict 缓存，cosine 相似度 ≥ 0.95 命中，TTL 5 分钟
- **理由**：query 微小变化（如「退款几天」vs「退款要几天」）仍能命中
- **限制**：无持久化、无 LRU 淘汰（每 KB 上限 100 条，内存可控）

### D5: 并行改写
- **决策**：禁止。Rewrite 全链路串行（无 embed 并行），Rerank 仅一次 LLM 调用
- **理由**：简单可靠；Rerank 若拆多个子批次并行会引入排序合并复杂度

## Risks / Trade-offs

| 风险 | 影响 | 缓解 |
|------|------|------|
| 冷 query 延迟 ~2-4s | 用户体验下降 | 缓存消除重复；独立开关默认禁用；`max_candidates: 20` 控 payload |
| LLM API 不稳定 | 检索失败 | 降级回原始排序/原始 query，不中断接口 |
| 模型响应非 JSON | 无法解析 | 4 层 JSON 防御（`json_object` 模式 + try-parse + regex + 默认值）|
| 缓存内存泄漏 | OOM | 每 KB 上限 100 条 + TTL 5min + KB 写入清空 |
