## Why

当前 RAGNexus 纯向量检索链路已经能召回相关 chunk，但存在两个问题：
1. **排序质量**：向量相似度排序不总能反映真实语义相关性，靠前的 chunk 未必最有用
2. **查询质量**：用户 query 常口语化、含指代词、过于简短，直接 embedding 检索效果差

这两个问题可以通过 LLM 介入优化，且对调用方完全透明——HTTP 契约零变更。

## What Changes

### 新增能力

- **LLM 重排（Rerank）**：向量召回后、返回前，插入 LLM 打分重排环节，优化排序质量
- **查询改写（Query Rewrite）**：Embedding 前介入，将口语化/模糊 query 改写为更适合向量检索的形式

### 新增代码

| 路径 | 用途 |
|------|------|
| `src/ragnexus/adapters/llm/` | 通用大模型调用抽象（`LLMProvider` ABC + `OpenAICompatibleLLMProvider` 实现） |
| `src/ragnexus/adapters/rerank/` | 重排实现（`NoopRerankProvider` + `LLMRerankProvider`） |
| `src/ragnexus/adapters/rewrite/` | 查询改写实现（`NoopRewriteProvider` + `LLMRewriteProvider`） |

### 修改文件

| 文件 | 改动 |
|------|------|
| `src/ragnexus/config.py` | 新增 `LLM_*` + `RERANK_*` + `REWRITE_*` 配置字段 |
| `src/ragnexus/domain/ports.py` | 新增 `RerankPort` + `RewritePort` Protocol |
| `src/ragnexus/application/retrieve_use_case.py` | 注入 `Rewriter` + `Reranker`；嵌入 rewrite + rerank 步骤 |
| `src/ragnexus/composition.py` | 创建 `LLMProvider` + `RerankProvider` + `RewriteProvider` 实例 |
| `.env.example` | 同步新增配置项 |

### 不修改

- HTTP 请求/响应 schema（完全零变化）
- `domain/models.py`（`SearchHit` 不加字段）
- `adapters/http/retrieve_router.py`
- 现有 5 个 Port 签名
- `retrieve_logs` 表

### 权衡

- **两者全开时冷 query 延迟 ~2-4s**（两次 LLM 调用），缓存命中后降回基线。用户应知此权衡，通过 `.env` 独立开关控制
- Embed 基线延迟取决于具体 provider（如 BAAI/bge-m3 ~200ms，OpenAI text-embedding-3-small ~500ms）

## Capabilities

### New Capabilities

- `llm-rerank`: LLM 驱动的检索结果重排序。向量召回后、返回前介入，对候选 chunk 进行 LLM 相关性打分并重新排序。支持缓存（向量相似 ≥ 0.95）、降级、独立开关
- `query-rewrite`: LLM 驱动的查询改写。Embedding 前介入，对口语化/模糊 query 判断是否需要改写并执行改写。支持缓存、降级、独立开关
- `llm-provider`: 通用大模型调用基础设施。被 rerank/rewrite 共享使用，支持 OpenAI 兼容 API、并发控制、指数退避重试

### Modified Capabilities

- 无。现有 `vector-retrieval` 和 `document-ingestion` 能力的 HTTP 契约和行为语义不变
