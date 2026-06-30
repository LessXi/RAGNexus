# Comet Design Handoff

- Change: llm-rerank-and-rewrite
- Phase: design
- Mode: compact
- Context hash: 69c233c7218e0a608c66ba866183d2da5c4bdd735801148b7748a513f760ef57

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/llm-rerank-and-rewrite/proposal.md

- Source: openspec/changes/llm-rerank-and-rewrite/proposal.md
- Lines: 1-57
- SHA256: 2a2e26402ff3d1763150cb197f2fa6e4e6a9b4cf9f3ff5e5b3541e9b91d4dbd8

```md
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
```

## openspec/changes/llm-rerank-and-rewrite/design.md

- Source: openspec/changes/llm-rerank-and-rewrite/design.md
- Lines: 1-107
- SHA256: 98c334d5f6bea2f40833cf2f0c2aa7c712767bab69d93e9f8645c964b314ab89

[TRUNCATED]

```md
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
```

Full source: openspec/changes/llm-rerank-and-rewrite/design.md

## openspec/changes/llm-rerank-and-rewrite/tasks.md

- Source: openspec/changes/llm-rerank-and-rewrite/tasks.md
- Lines: 1-46
- SHA256: ebec9196702caa3ed6df5d632d9b5cd7a17293b78ecea6c5fcd6c19f34350a55

```md
## 1. 基础设施层

- [ ] 1.1 config.py 新增 `LLM_*` + `RERANK_*` + `REWRITE_*` 配置字段
- [ ] 1.2 .env.example 新增 `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`/`LLM_REQUEST_TIMEOUT`/`LLM_CONNECT_TIMEOUT`/`LLM_MAX_CONCURRENCY`/`LLM_MAX_RETRIES`/`LLM_RETRY_BACKOFF_BASE` + `RERANK_ENABLED`/`RERANK_CANDIDATE_MULTIPLIER`/`RERANK_MIN_CANDIDATES`/`RERANK_MAX_CANDIDATES`/`RERANK_CHUNK_MAX_CHARS`/`RERANK_TEMPERATURE` + `REWRITE_ENABLED`（约 16 行）
- [ ] 1.3 创建 `adapters/llm/base.py` — `LLMProvider` ABC（`chat_json` 抽象方法）
- [ ] 1.4 创建 `adapters/llm/openai_compatible.py` — `OpenAICompatibleLLMProvider`（httpx 惰性初始化、Semaphore、指数退避重试）
- [ ] 1.5 实现 `_call_api` 方法和 `log_model_call` 桥接

## 2. 领域层 — Rerank

- [ ] 2.1 `domain/ports.py` 新增 `RerankPort` Protocol（`rerank` + `clear_cache` 方法签名）

## 3. 重排实现

- [ ] 3.1 创建 `adapters/rerank/noop.py` — `NoopRerankProvider`（直通）
- [ ] 3.2 创建 `adapters/rerank/llm.py` — `LLMRerankProvider`（含：缓存逻辑、LLM 调用、候选截断、JSON 4 层防御、降级、BIZ_EVENT 日志）

## 4. 链路集成 — Rerank

- [ ] 4.1 `RetrieveUseCase` 注入 `RerankPort` + `candidate_multiplier` + `min_candidates`
- [ ] 4.2 `RetrieveUseCase.execute()` 插入 rerank 步骤（向量召回后、返回前）
- [ ] 4.3 `composition.py` 装配 `LLMProvider` + `RerankProvider` 并注入 use case
- [ ] 4.4 composition.py 包装 upload_doc 调用成功后清空 rerank 缓存

## 5. 领域层 + 实现 — Rewrite

- [ ] 5.1 `domain/ports.py` 新增 `RewritePort` Protocol + `RewriteResult` dataclass
- [ ] 5.2 创建 `adapters/rewrite/noop.py` — `NoopRewriteProvider`（直通）
- [ ] 5.3 创建 `adapters/rewrite/llm.py` — `LLMRewriteProvider`（含：缓存逻辑、一次 LLM 判断+改写、5 层防御、降级、reason 仅日志、BIZ_EVENT 日志）

## 6. 链路集成 — Rewrite

- [ ] 6.1 `RetrieveUseCase` 注入 `RewritePort`
- [ ] 6.2 `RetrieveUseCase.execute()` 插入 rewrite 步骤（embed 之前）
- [ ] 6.3 `composition.py` 装配 `RewriteProvider` 并注入 use case
- [ ] 6.4 composition.py 包装 upload_doc 调用后清空 rewrite 缓存

## 7. 测试

- [ ] 7.1 单元测试：LLMProvider（mock httpx 响应、超时、JSON 解析）
- [ ] 7.2 单元测试：LLMRerankProvider（正常重排、缓存命中/部分命中、LLM 降级）
- [ ] 7.3 单元测试：LLMRewriteProvider（需要改写、不需要改写、LLM 降级）
- [ ] 7.4 单元测试：NoopRerankProvider / NoopRewriteProvider 直通行为
- [ ] 7.5 集成测试：RetrieveUseCase 全链路（Rewrite + Rerank 组合）
- [ ] 7.6 验证测试：HTTP 请求/响应 schema 完全不变（断言请求无新增字段、响应格式与第一期一致）
- [ ] 7.7 E2E 测试：POST /v1/rag:retrieve 启用/禁用各优化
```

## openspec/changes/llm-rerank-and-rewrite/specs/llm-rerank/spec.md

- Source: openspec/changes/llm-rerank-and-rewrite/specs/llm-rerank/spec.md
- Lines: 1-80
- SHA256: b731a0e897a0d8fe2bb27cd12c3da805f25bd1ebf978717c87a96c5213b87e9f

```md
## ADDED Requirements

### Requirement: 重排启用开关
系统 MUST 通过 `RERANK_ENABLED` 配置项控制是否启用 LLM 重排。默认值 MUST be `false`（禁用）。

#### Scenario: 禁用时直通
- **WHEN** `RERANK_ENABLED=false`（默认）
- **THEN** 检索结果 MUST 直接返回向量排序结果，不做重排

#### Scenario: 启用时执行重排
- **WHEN** `RERANK_ENABLED=true`
- **THEN** 向量召回后、返回前，MUST 执行 LLM 重排

### Requirement: HTTP 契约零变化
重排 MUST NOT 改变 `POST /v1/rag:retrieve` 的请求 schema、响应 schema 或 `score` 语义。

#### Scenario: 请求不变
- **WHEN** 调用方发送检索请求
- **THEN** 请求体格式（`query` / `kb_ids` / `top_k`）MUST 与第一期完全一致
- **THEN** 请求体 MUST NOT 包含任何重排相关字段

#### Scenario: 响应不变
- **WHEN** 调用方收到检索响应
- **THEN** 响应体格式 MUST 与第一期完全一致
- **THEN** `hits[].score` MUST 始终为向量原始分（1 - cosine distance），MUST NOT 被重排覆盖
- **THEN** 响应 MUST NOT 包含 `rerank_score` 或任何重排相关字段
- **THEN** `hits` 的排列顺序 MAY 受重排影响，但调用方 MUST NOT 能感知差异

### Requirement: `top_k` 语义不变
`top_k` MUST 始终等于最终返回的 chunk 数量。

#### Scenario: 候选数计算
- **WHEN** 启用重排
- **THEN** 内部 MUST 召回更多候选：`candidate_k = max(top_k × candidate_multiplier, top_k + min_candidates)`
- **THEN** 重排后 MUST 裁回 `top_k` 条返回
- **WHEN** 禁用重排
- **THEN** `candidate_k` MUST 等于 `top_k`（不额外召回）

### Requirement: LLM 调用降级
LLM 重排 MUST 保证接口不因 LLM 不可用而中断。

#### Scenario: LLM 调用失败
- **WHEN** LLM 调用超时、返回错误、或 JSON 解析失败
- **THEN** MUST 返回原始向量排序结果，MUST NOT 抛异常
- **THEN** 降级决策 MUST 在 LLMRerankProvider 内部完成，MUST NOT 传播到 use case 或 HTTP 层

### Requirement: 重排缓存
系统 MUST 提供重排缓存，对相同或相似的 query 避免重复 LLM 调用。

#### Scenario: 缓存命中
- **WHEN** 当前 query 的向量与缓存中某条目的向量 cosine 相似度 ≥ 0.95
- **THEN** MUST 直接使用缓存分，跳过 LLM 调用

#### Scenario: 部分命中
- **WHEN** 部分候选 chunk 有缓存分、部分没有
- **THEN** 未命中的 chunk MUST 送 LLM 打分，缓存的 chunk 分 MUST 作为 Prompt 标尺参考

#### Scenario: KB 写入失效
- **WHEN** 某 KB 的文档上传完成
- **THEN** MUST 清空该 KB 的全部缓存条目

### Requirement: 候选截断
LLM 重排的输入候选数 MUST 有上限，防止 payload 过大。

#### Scenario: 候选上限
- **WHEN** `candidate_k` 计算值超过 `max_candidates`（默认 20）
- **THEN** MUST 截断为 `max_candidates` 条
- **WHEN** 截断发生
- **THEN** MUST 优先保留向量分最高的候选

### Requirement: 日志记录
重排过程 MUST 输出结构化日志，支持运维排查。

#### Scenario: 日志输出
- **WHEN** 重排完成
- **THEN** MUST 记录 `BIZ_EVENT` 事件，包含：query、候选数、LLM 是否调用、缓存命中率、耗时
- **WHEN** LLM 调用失败
- **THEN** MUST 记录 `BIZ_EVENT` 事件，标记降级原因

> 实现参考: `docs/4-llm-rerank-silent-judge.md`（739 行工程规范）
```

## openspec/changes/llm-rerank-and-rewrite/specs/query-rewrite/spec.md

- Source: openspec/changes/llm-rerank-and-rewrite/specs/query-rewrite/spec.md
- Lines: 1-67
- SHA256: aa3c5b5e88615c57279184dd4bee44e0e60f4fe6def443da311e23348f1f1f43

```md
## ADDED Requirements

### Requirement: 改写启用开关
系统 MUST 通过 `REWRITE_ENABLED` 配置项控制是否启用查询改写。默认值 MUST be `false`（禁用）。

#### Scenario: 禁用时直通
- **WHEN** `REWRITE_ENABLED=false`（默认）
- **THEN** 检索 MUST 使用原始 query 进行 embedding，不做改写

#### Scenario: 启用时执行改写
- **WHEN** `REWRITE_ENABLED=true`
- **THEN** embedding 之前 MUST 执行查询改写

### Requirement: HTTP 契约零变化
查询改写 MUST NOT 改变 `POST /v1/rag:retrieve` 的请求 schema 或响应 schema。调用方 MUST NOT 能感知差异。

#### Scenario: 请求不变
- **WHEN** 调用方发送检索请求
- **THEN** 请求体格式 MUST 与第一期完全一致

#### Scenario: 响应不变
- **WHEN** 调用方收到检索响应
- **THEN** 响应体格式 MUST 与第一期完全一致
- **THEN** 响应 MUST NOT 包含改写相关信息（如 `original_query`、`rewritten_query`）

### Requirement: 一次 LLM 调用完成判断和改写
系统 MUST 在一次 LLM 调用中同时完成"是否需要改写"的判断和"执行改写"。

#### Scenario: 需要改写
- **WHEN** 查询包含口语化表达、指代词、或语义模糊
- **THEN** LLM MUST 输出 `needs_rewrite: true` 和 `rewritten_query`
- **THEN** embedding MUST 使用改写后的 query

#### Scenario: 不需要改写
- **WHEN** 查询已包含明确的关键词、专业术语，语义清晰
- **THEN** LLM MUST 输出 `needs_rewrite: false` 和 `rewritten_query` 等于原始 query
- **THEN** embedding MUST 使用原始 query

### Requirement: LLM 调用降级
查询改写 MUST 保证接口不因 LLM 不可用而中断。

#### Scenario: LLM 调用失败
- **WHEN** LLM 调用超时、返回错误、或 JSON 解析失败
- **THEN** MUST 使用原始 query，MUST NOT 抛异常
- **THEN** 降级决策 MUST 在 LLMRewriteProvider 内部完成

### Requirement: 改写缓存
系统 MUST 提供改写缓存，对相同或相似的 query 避免重复 LLM 调用。

#### Scenario: 缓存命中
- **WHEN** 当前 query 的向量与缓存中某条目的向量 cosine 相似度 ≥ 0.95
- **THEN** MUST 直接使用缓存的改写结果，跳过 LLM 调用

#### Scenario: KB 写入失效
- **WHEN** 某 KB 的文档上传完成
- **THEN** MUST 清空该 KB 的全部改写缓存

### Requirement: `reason` 字段仅日志使用
LLM 返回的改写原因 MUST NOT 影响业务逻辑。

#### Scenario: reason 不影响逻辑
- **WHEN** LLM 返回 `reason` 字段
- **THEN** 该字段 MUST 仅用于日志记录，MUST NOT 影响改写结果的输出
- **WHEN** `reason` 为空或缺失
- **THEN** MUST NOT 触发降级，MUST NOT 影响 rewrite 结果

> 实现参考: `docs/5-query-rewrite-silent-scribe.md`（320 行工程规范）
```

