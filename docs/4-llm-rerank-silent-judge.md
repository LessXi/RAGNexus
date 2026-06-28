# RAGNexus 第二期：大模型重排 — 工程规范

> **第二期目标**：在现有纯向量检索链路上，增加**对调用方透明**的大模型重排能力。
> - HTTP 契约**零变化**（请求/响应和第一期一模一样）
> - 重排通过 `.env` 全局开关控制，对调用方完全无感知
> - 降级自动回退向量排序，不中断接口
> - 新增 `LLMProvider` 通用大模型调用抽象（后续 query rewrite、意图识别等复用）

---

## Context

第一期骨架已实现 `POST /v1/rag:retrieve` 的纯向量检索链路（embedding → pgvector 召回 → 返回 top_k chunks）。本期在此基础上增加**后台透明重排**：

- 向量召回后、返回前，插入 LLM 打分重排环节
- HTTP 层请求/响应**不做任何改动**，调用方不知道重排的存在
- 调用方只看到：同样的请求，结果相关性变好了
- 排查走结构化日志，不污染接口响应

**预期产出**：配好 `.env` 的 `RERANK_ENABLED=true` + LLM 相关字段 → 重启服务 → 检索结果自动经过 LLM 重排。

---

## 1. 接口契约

### 1.1 请求 — 零变化

```json
{
  "query": "退款需要几天内申请？",
  "kb_ids": ["kb_xxx"],
  "top_k": 5
}
```

与第一期 `POST /v1/rag:retrieve` **完全相同**。无 `rerank_options`、无 `rerank` 开关、无新增字段。

### 1.2 响应 — 零变化

```json
{
  "code": 0,
  "data": {
    "total": 5,
    "hits": [
      {
        "chunk_id": "chunk_001",
        "kb_id": "kb_xxx",
        "doc_id": "doc_001",
        "score": 0.86,
        "text": "用户可在订单完成后 7 天内申请退款。",
        "metadata": {}
      }
    ]
  },
  "message": "ok"
}
```

**关键语义**：
- `score` 始终是向量原始分（1 - cosine distance），**不被重排覆盖**
- `hits` 的**排列顺序**受重排影响（启用重排后按 LLM 打分排序），但调用方看不到任何区别
- 无 `rerank_score` 字段，无 `metadata.rerank` 字段

### 1.3 `top_k` 语义 — 不变

`top_k` = 最终返回的 chunk 数量。启用重排后内部召回更多候选（`candidate_k`），重排后裁回 `top_k` 返回。

---

## 2. 技术栈

本期**不引入新依赖**。现有依赖已覆盖：

| 能力 | 用到的现有依赖 |
|------|-------------|
| LLM HTTP 调用 | `httpx`（已有） |
| 异步并发控制 | `asyncio.Semaphore`（标准库） |
| 重试 | 手动指数退避（embeder 已实现同样模式） |
| JSON 解析 | `json`（标准库）+ `re`（标准库） |

---

## 3. 架构与目录

### 3.1 不变的部分

- 六边形架构方向不变（domain 不 import adapters）
- `domain/models.py` 不变（`SearchHit` 不加字段）
- `domain/ports.py` 中现有 5 个 Port 不动
- `adapters/http/retrieve_router.py` 请求/响应 schema 不动
- `retrieve_logs` 表不动

### 3.2 新增目录

```
adapters/
├── llm/                               # 通用大模型调用（本期新增）
│   ├── __init__.py
│   ├── base.py                        # LLMProvider ABC
│   └── openai_compatible.py           # OpenAICompatibleLLMProvider
├── rerank/                            # 重排能力（本期新增）
│   ├── __init__.py
│   ├── noop.py                        # NoopRerankProvider（直通）
│   └── llm.py                         # LLMRerankProvider（依赖 LLMProvider）
```

### 3.3 修改文件

| 文件 | 改动 |
|------|------|
| `config.py` | 新增 `LLM_*` + `RERANK_*` 配置字段 |
| `.env.example` | 同步新增配置项 |
| `domain/ports.py` | 新增 `RerankPort` Protocol |
| `application/retrieve_use_case.py` | 注入 `RerankPort` + `candidate_multiplier`；在向量召回后插入 rerank 步骤 |
| `composition.py` | 创建 `LLMProvider` + `RerankProvider` 实例，注入 use case |

### 3.4 LLMProvider 用 `ABC`，与 `EmbedderPort(Protocol)` 风格说明

现有 `EmbedderPort` 在 `domain/ports.py` 中用 `typing.Protocol` — 这是六边形架构的领域端口惯例。`LLMProvider` 不在 domain 层 — 它是 adapters 层内部抽象（类似 httpx 的封装），用 `abc.ABC` 更合适：它包含共享的 HTTP client 管理逻辑（惰性初始化、semaphore、重试），`Protocol` 不适合承载这些。两者不冲突：**domain 端口用 Protocol，adapters 内部抽象用 ABC**。

---

## 4. Ports

```python
class RerankPort(Protocol):
    """重排端口 — 对向量召回候选 chunk 重排序。

    骨架实现: LLMRerankProvider (启用时), NoopRerankProvider (禁用时)。
    返回类型为 list[SearchHit] — 排好序，score 保持向量原始分不变。
    """

    async def rerank(
        self,
        *,
        query: str,
        query_vector: list[float],
        kb_ids: list[str],
        chunks: list[SearchHit],
        top_n: int,
    ) -> list[SearchHit]: ...

    async def clear_cache(self, kb_id: str) -> None:
        """清空指定 KB 的缓存。文档上传后由 composition.py 调用。

        NoopRerankProvider 实现为空。
        """
        ...
```

### 4.2 LLMProvider ABC（基础设施内部抽象）

```python
from abc import ABC, abstractmethod

class LLMProvider(ABC):
    """通用大模型调用抽象。所有 LLM 调用必须通过此接口。

    不定义在 domain/ports.py 中 — 这是 adapters 层内部抽象。
    后续 query rewrite、意图识别、评测辅助生成等也通过它调用大模型。
    """

    @abstractmethod
    async def chat_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict,
        temperature: float = 0.0,
        timeout_seconds: int | None = None,
    ) -> dict: ...
```

---

## 5. 重排数据流
```
POST /v1/rag:retrieve               ← 零变化
        │
        ▼
RetrieveUseCase.execute(query, kb_ids, top_k=5)
        │
        ├── 1. validate                ← 零变化
        ├── 2. embedder.embed([query]) ← 零变化（query_vector 也用于缓存查找）
        │
        ├── 3. 计算候选数
        │       candidate_k = max(top_k × candidate_multiplier,
        │                         top_k + min_candidates)
        │
        ├── 4. store.search_by_vector(query_vector, candidate_k, kb_ids)
        │
        ├── 5. reranker.rerank(query, query_vector, kb_ids, chunks, top_n=top_k)
        │       │ LLMRerankProvider                            │
        │       │  a) 查缓存（向量相似 ≥ 阈值）                  │
        │       │      ├── 全命中 → 直接排序返回，跳过 b-e       │
        │       │      ├── 部分命中 → 拆 matched/unmatched      │
        │       │      │     matched 用缓存分，unmatched 送 LLM  │
        │       │      │     Prompt 带 reference_scores 标尺    │
        │       │      └── 全 miss ↓                           │
        │       │  b) 候选截断（max_candidates，默认 20）        │
        │       │  c) 文本截断（chunk_max_chars，默认 1000）     │
        │       │  d) 构造 JSON payload（含 candidates）         │
        │       │  e) LLMProvider.chat_json()                   │
        │       │  f) 解析 rankings → 合并 → 排序 → 裁回 top_n   │
        │       │  g) 写入缓存（全量 15 条 + query_embedding）   │
        │       │  h) 降级时返回原始向量排序                     │
        │       └──────────────────────────────────────────────┘
        │
        └── 6. return hits (SearchHit[])  ← 零变化
```

- `candidate_multiplier` 和 `min_candidates` 由 composition.py 注入 use case 构造器
- `NoopRerankProvider` 场景注入 `multiplier=1, min=0` → `candidate_k = top_k`

### 5.2 Reranker 内部流程


**输入**：`query`（原始用户问题）、`query_vector`（已嵌入的向量，复用 Step 2）、`kb_ids`（检索目标 KB 列表，用于缓存分区）、`chunks`（向量召回的 SearchHit 列表，按 score 降序）、`top_n`（最终返回数 = top_k）

| 步骤 | 操作 | 说明 |
|------|------|------|
| a | 查缓存：遍历 `_cache[kb_id]`，逐个算 cosine(query_vector, entry.query_embedding) | 阈值 ≥ 0.95 |
| a1 | 全命中（缓存覆盖所有 chunk_id）→ 直接按缓存分排序返回 | 跳过 b-e，零 LLM 调用 |
| a2 | 部分命中 → 拆 `matched`（用缓存分）+ `unmatched`（送 LLM）| Prompt 注入 `reference_scores` 标尺，见 §5.3 |
| b | `unmatched = unmatched[:max_candidates]` | 仅对未命中候选截断 |
| c | `chunk.text = chunk.text[:chunk_max_chars]` | 每个 chunk 截断到 1000 字符 |
| d | 构造 JSON payload（含 `candidates` + `reference_scores`）| 见 §6.2 |
| e | `await self.llm.chat_json(...)` | 见 §6.1 |
| f | 解析 `rankings` → 与缓存分合并 → 排序 → 裁回 `top_n` | 未命中 chunk 默认 score=0；LLM 漏掉的 chunk 也默认 0 |
| g | 写入缓存：缓存全部 `chunk_id → score` 映射 + `query_embedding` | 超 maxsize 时踢最旧条目 |
| h | 降级 | 任意步骤抛异常 → 返回 `chunks[:top_n]`（原始向量排序） |

**输出**：`list[SearchHit]` — 排好序，`score` 字段仍然是向量原始分。

### 5.3 缓存设计

**命中策略**：向量余弦相似度。用 Step 2 已有的 `query_embedding` 与缓存中每条 `entry.query_embedding` 逐一计算，取最高分。≥ 阈值 0.95 即命中。

**缓存条目结构**（自建 `dict[str, list[CacheEntry]]` + `asyncio.Lock`）：

```python
@dataclass
class CacheEntry:
    query_embedding: list[float]   # 1024 维，用于相似度匹配
    query_text: str                # 原始 query，用于日志
    rankings: dict[str, float]     # {chunk_id: rerank_score}
    timestamp: float               # 写入时间，用于 TTL 过期
```

**部分命中 — Prompt 标尺方案**：

缓存命中的 chunk 不重送 LLM。在 LLM 请求的 payload 中附加 `reference_scores` 作为标尺：

```json
{
  "query": "退款需要几天内申请？",
  "candidates": [
    {"chunk_id": "chunk_007", "content": "退款金额会在审核通过后退回。", "vector_score": 0.68}
  ],
  "reference_scores": [
    {"chunk_id": "chunk_001", "rerank_score": 0.92, "content_preview": "退款政策: 用户可在订单完成后 7 天内申请退款。"},
    {"chunk_id": "chunk_005", "rerank_score": 0.78, "content_preview": "特殊商品不支持无理由退款。"}
  ],
  "top_n": 5
}
```

`content_preview` 从 `SearchHit.text` 截取前几个完整句子（≤ 150 字符），前置 `heading`（如有）。不送 `reason`（避免 feedback loop）。

LLM 合并后，写入缓存的条目覆盖全部 15 个 chunk 的分数。下次相同 query 全量命中。

**配置参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `RERANK_CACHE_SIMILARITY_THRESHOLD` | 0.95 | 余弦相似度命中阈值 |
| `RERANK_CACHE_MAX_ENTRIES_PER_KB` | 100 | 每个 KB 最多缓存条目数 |
| `RERANK_CACHE_TTL_SECONDS` | 300 | TTL 兜底（5 分钟），KB 写入时主动清空优先 |
| `RERANK_CACHE_PREVIEW_MAX_CHARS` | 150 | `content_preview` 截断长度 |

**失效策略**：

| 触发条件 | 操作 |
|----------|------|
| KB 中文档上传 | composition.py 调 `reranker.clear_cache(kb_id)` |
| TTL 过期 | 查找时过滤 `now - entry.timestamp > ttl` |
| 超过 maxsize | `_cache[kb_id]` 条目数 > `max_entries_per_kb` → 踢最旧的 |


---

## 6. LLM 调用协议

### 6.1 请求格式

通过 OpenAI-compatible `/chat/completions` 端点发送：

```json
{
  "model": "deepseek-chat",
  "messages": [
    {
      "role": "system",
      "content": "你是 RAG 检索重排器。你的任务是根据用户问题，对候选知识片段进行相关性打分和排序。\n\n要求：\n1. 只判断候选片段是否有助于回答用户问题。\n2. 不要回答用户问题。\n3. 不要编造候选片段中不存在的信息。\n4. 每个候选片段给出 0 到 1 之间的 rerank_score。\n5. 分数越高表示越相关、越适合作为 RAG 上下文。\n6. 只返回 JSON，不要返回 Markdown，不要返回解释性文字。\n7. reference_scores 中的候选已有最终相关性分数。请在相同评分体系下为 candidates 打分，保持分数的一致性和可比性。不要更改或质疑 reference_scores 中的分数。"
    },
    {
      "role": "user",
      "content": "<JSON payload 字符串>"
    }
  ],
  "temperature": 0,
  "response_format": { "type": "json_object" }
}


### 6.2 传给 LLM 的 JSON payload

**全部候选**（缓存全 miss 场景）：

```json
{
  "query": "退款需要几天内申请？",
  "candidates": [
    {
      "chunk_id": "chunk_001",
      "document_id": "doc_001",
      "title": "退款政策",
      "content": "用户可在订单完成后 7 天内申请退款。",
      "vector_score": 0.86
    }
  ],
  "top_n": 5
}
```

**部分命中场景**（带 `reference_scores` 标尺）：

```json
{
  "query": "退款需要几天内申请？",
  "candidates": [
    {"chunk_id": "chunk_007", "document_id": "doc_002", "title": "退款流程", "content": "退款金额会在审核通过后退回。", "vector_score": 0.68}
  ],
  "reference_scores": [
    {"chunk_id": "chunk_001", "rerank_score": 0.92, "content_preview": "退款政策: 用户可在订单完成后 7 天内申请退款。"}
  ],
  "top_n": 5
}
```

> `reference_scores` 仅在缓存部分命中时出现。`content_preview` 为智能截断（前几个完整句子，≤ 150 字符，前置 heading）。不送 `reason`。

| 字段 | 来源 | 约束 |
|------|------|------|
| `chunk_id` | `SearchHit.chunk_id` | |
| `document_id` | `SearchHit.doc_id` | |
| `title` | `SearchHit.metadata["heading"]` or `""` | `None` 时传空字符串，不传 `null` |
| `content` | `SearchHit.text[:chunk_max_chars]` | ≤ 1000 字符 |
| `vector_score` | `SearchHit.score` | 原始向量分，供 LLM 参考 |
| `top_n` | = `top_k` | 期望返回数量 |

**candidates 保持向量召回原始顺序**（score 从高到低）。不 shuffle。

### 6.3 期望 LLM 返回

```json
{
  "rankings": [
    {
      "chunk_id": "chunk_001",
      "rerank_score": 0.95,
      "reason": "直接回答了退款时限。"
    },
    {
      "chunk_id": "chunk_005",
      "rerank_score": 0.32,
      "reason": "与退款限制有关但未回答时限。"
    }
  ]
}
```

| 字段 | 必须 | 说明 |
|------|------|------|
| `rankings` | 是 | 数组，每个候选一个打分 |
| `chunk_id` | 是 | 对应输入 candidates 中的 chunk_id |
| `rerank_score` | 是 | 0~1 之间的相关性分数 |
| `reason` | 否 | 打分原因，仅写日志，不暴露给业务 |

---

## 7. JSON 解析防御

`chat_json()` 返回前，对 LLM 输出进行 4 层解析：

| 层级 | 操作 | 覆盖场景 |
|------|------|---------|
| 0 | API 层 `response_format: json_object` | DeepSeek/OpenAI 原生强制 JSON 输出 |
| 1 | `json.loads(content)` | LLM 正常返回纯 JSON |
| 2 | 正则提取 ` ```json ... ``` ` | LLM 包了 markdown 代码块 |
| 3 | 正则提取最外层 `{...}` | 文本中夹杂 JSON |
| 4 | 抛 `AppError(MODEL_NO_RESPONSE)` | 全失败 → catch → 降级 |

**边界处理**：
- LLM 返回了不存在的 `chunk_id` → **忽略**，不抛异常
- LLM 漏掉了某些 chunk → 默认 `rerank_score = 0.0`
- `rerank_score` 超出 [0,1] → clamp 到 [0,1]

---

## 8. 降级策略

### 8.1 降级责任链

```
LLMRerankProvider.rerank()
  ├── chat_json() 抛 AppError
  │     → logger.warning("rerank LLM 调用失败，降级为向量排序")
  │     → logger.info(BIZ_EVENT: rerank_degraded)
  │     → return chunks[:top_n]  ← 原始向量排序
  │
  ├── JSON 解析失败
  │     → 同上
  │
  └── LLM 超时
        → httpx.TimeoutException → AppError(MODEL_TIMEOUT)
        → 同上
```

### 8.2 关键约束

- `LLMRerankProvider.rerank()` **永远不抛异常** → use case 不需要 try/except 包裹
- embedding 失败 → 接口可以 5xx（基础设施故障）
- rerank 失败 → 接口正常 200，结果按向量排序返回
- `NoopRerankProvider.rerank()` 直接 `return chunks[:top_n]`

---

## 9. 日志

### 9.1 retrieve_logs 表 — 不动

现有 `retrieve_logs` 表不加列。`top_k` 记录请求传入值（非 `candidate_k`）。`latency_ms` 包含全链路（embed + 向量召回 + rerank）。

### 9.2 结构化日志 — 新增 3 条

**重排成功**：

```python
logger.info("", extra={
    "event_type": "BIZ_EVENT",
    "event": "rerank_completed",
    "kb_ids": kb_ids,
    "query": query[:200],
    "candidate_count": 15,
    "kept_count": top_n,
    "rerank_latency_ms": 567,
})
```

**重排降级**：

```python
logger.warning("rerank LLM 调用失败，降级为向量排序", extra={
    "event_type": "BIZ_EVENT",
    "event": "rerank_degraded",
    "kb_ids": kb_ids,
    "query": query[:200],
    "candidate_count": len(chunks),
    "error_type": "ModelTimeout",
    "error_message": "LLM 响应超时",
})
```

**打分详情**（DEBUG 级别，仅落文件不输出到控制台）：

```python
logger.debug("rerank 打分详情", extra={
    "event_type": "RERANK_DEBUG",
    "kb_ids": kb_ids,
    "query": query[:200],
    "rankings": [
        {"chunk_id": "chunk_001", "rerank_score": 0.95, "reason": "直接回答了退款时限。"},
        {"chunk_id": "chunk_005", "rerank_score": 0.32, "reason": "不相关"},
    ],
})
```


**缓存命中**：

```python
logger.info("", extra={
    "event_type": "BIZ_EVENT",
    "event": "rerank_cache_hit",
    "kb_ids": kb_ids,
    "query": query[:200],
    "similarity": 0.96,
    "cached_query": "怎么申请退款",
    "matched_count": 13,
    "unmatched_count": 2,
})
```

**缓存未命中**：

```python
logger.debug("rerank 缓存未命中", extra={
    "event_type": "RERANK_DEBUG",
    "kb_ids": kb_ids,
    "query": query[:200],
    "max_similarity": 0.72,
    "cached_queries_checked": 42,
})
```

### 9.3 LLM 调用日志 — `@log_model_call` 适配

`log_model_call` 装饰器通过 `prompt_arg` 索引位置参数。但 `chat_json()` 的 `user_payload` 在 `*` 后面（keyword-only），不是位置参数。因此新增一个内部 `_call_api` 方法来桥接：

```python
class OpenAICompatibleLLMProvider:
    @log_model_call("deepseek-chat", prompt_arg=1)
    async def _call_api(self, payload_str: str, *, timeout_seconds: int | None = None) -> dict:
        """实际 HTTP 调用 — prompt_arg=1 索引 payload_str。"""
        ...

    async def chat_json(self, *, system_prompt, user_payload, temperature=0.0, timeout_seconds=None):
        payload_str = json.dumps(user_payload, ensure_ascii=False)
        return await self._call_api(payload_str, timeout_seconds=timeout_seconds)
```

与现有 embedder 的 `@log_model_call("text-embedding-v3", prompt_arg=1)` 完全一致的日志格式（MODEL_REQUEST → MODEL_RESPONSE + cost_ms），端到端可观测性无断层。

---

## 10. 配置

### 10.1 config.py 新增字段

LLM 配置字段与 embedder 保持相同模式（`BASE_URL`/`API_KEY`/`MODEL` + `REQUEST_TIMEOUT`/`CONNECT_TIMEOUT` + `MAX_CONCURRENCY`/`MAX_RETRIES`/`RETRY_BACKOFF_BASE`）：

```python
# --- LLM (通用大模型调用) ---
LLM_BASE_URL: str = "https://opencode.ai/zen/v1"
LLM_API_KEY: str = ""
LLM_MODEL: str = "deepseek-v4-flash-free"
LLM_REQUEST_TIMEOUT: float = 60.0
LLM_CONNECT_TIMEOUT: float = 5.0
LLM_MAX_CONCURRENCY: int = 5
LLM_MAX_RETRIES: int = 2
LLM_RETRY_BACKOFF_BASE: float = 2.0

# --- Rerank ---
RERANK_ENABLED: bool = False
RERANK_MAX_CANDIDATES: int = 20
RERANK_CANDIDATE_MULTIPLIER: int = 3
RERANK_MIN_CANDIDATES: int = 10
RERANK_CHUNK_MAX_CHARS: int = 1000
RERANK_TEMPERATURE: float = 0.0

# --- Rerank 缓存 ---
RERANK_CACHE_SIMILARITY_THRESHOLD: float = 0.95
RERANK_CACHE_MAX_ENTRIES_PER_KB: int = 100
RERANK_CACHE_TTL_SECONDS: int = 300
RERANK_CACHE_PREVIEW_MAX_CHARS: int = 150
```

### 10.2 .env 示例

```bash
# --- LLM ---
LLM_BASE_URL=https://opencode.ai/zen/v1
LLM_API_KEY=your-zen-api-key
LLM_MODEL=deepseek-v4-flash-free

# --- Rerank ---
RERANK_ENABLED=true
```

### 10.3 供应商切换

**OpenCode Zen**（默认，含免费模型）：

```bash
LLM_BASE_URL=https://opencode.ai/zen/v1
LLM_MODEL=deepseek-v4-flash-free
```

**DeepSeek 官方**：

```bash
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

**百炼 DashScope**：

```bash
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
```

---

## 11. DI 装配

```python
# composition.py — lifespan() 中新增

# LLM Provider（构造参数与 embedder 同模式）
llm_provider = OpenAICompatibleLLMProvider(
    base_url=cfg.LLM_BASE_URL,
    api_key=cfg.LLM_API_KEY,
    model=cfg.LLM_MODEL,
    request_timeout=cfg.LLM_REQUEST_TIMEOUT,
    connect_timeout=cfg.LLM_CONNECT_TIMEOUT,
    max_concurrency=cfg.LLM_MAX_CONCURRENCY,
    max_retries=cfg.LLM_MAX_RETRIES,
    retry_backoff_base=cfg.LLM_RETRY_BACKOFF_BASE,
)

# Rerank Provider
if cfg.RERANK_ENABLED:
    reranker = LLMRerankProvider(
        llm_provider=llm_provider,
        max_candidates=cfg.RERANK_MAX_CANDIDATES,
        chunk_max_chars=cfg.RERANK_CHUNK_MAX_CHARS,
        temperature=cfg.RERANK_TEMPERATURE,
        cache_threshold=cfg.RERANK_CACHE_SIMILARITY_THRESHOLD,
        cache_max_entries_per_kb=cfg.RERANK_CACHE_MAX_ENTRIES_PER_KB,
        cache_ttl_seconds=cfg.RERANK_CACHE_TTL_SECONDS,
        cache_preview_max_chars=cfg.RERANK_CACHE_PREVIEW_MAX_CHARS,
    )
    candidate_multiplier = cfg.RERANK_CANDIDATE_MULTIPLIER
    min_candidates = cfg.RERANK_MIN_CANDIDATES
else:
    reranker = NoopRerankProvider()
    candidate_multiplier = 1
    min_candidates = 0

# RetrieveUseCase
retrieve_uc = RetrieveUseCase(
    kb_repo=kb_repo,
    embedder=embedder,
    store=store,
    log_port=log_repo,
    reranker=reranker,
    candidate_multiplier=candidate_multiplier,
    min_candidates=min_candidates,
)
```

> `candidate_multiplier` 和 `min_candidates` 是构造参数，不是 config 依赖。use case 不读 `cfg.RERANK_ENABLED` 或任何 Settings 字段。

---

## 12. 性能与并发

### 12.1 并发控制

`OpenAICompatibleLLMProvider` 内部使用 `asyncio.Semaphore` 控制并发 LLM 调用数（`LLM_MAX_CONCURRENCY`，默认 5）。与 embedder 的并发控制模式完全一致。

rerank 场景每次请求只调用一次 LLM（单次 chat completion 处理所有候选 chunk），因此信号量主要防止多个并发检索请求同时打爆 LLM API。

### 12.2 超时

| 超时 | 配置 | 默认 | 说明 |
|------|------|------|------|
| 连接超时 | `LLM_CONNECT_TIMEOUT` | 5s | TCP 握手 |
| 请求超时 | `LLM_REQUEST_TIMEOUT` | 60s | 含响应体接收。chat completion 可能比 embedding 慢 |

### 12.3 重试

最多重试 `LLM_MAX_RETRIES` 次（默认 2 次，比 embedder 的 3 次更保守，因为 chat 更贵）。仅重试 429（Rate Limit）和 5xx（服务端错误）。4xx 不重试，直接抛异常 → 降级。

退避公式：`sleep(RETRY_BACKOFF_BASE ** attempt)` 秒。

### 12.4 资源清理

`OpenAICompatibleLLMProvider` 的 `httpx.AsyncClient` 在应用关闭时随 lifespan 自动清理。不需要显式 `close()` 调用。

---

## 13. 错误码

**不新增错误码**。LLM 调用异常映射到现有错误码，由 LLMRerankProvider catch 后降级，不传播到 HTTP 层。

| 场景 | ErrorCode | 传播范围 |
|------|-----------|---------|
| LLM HTTP 调用失败 | `MODEL_ERROR` (40000) | LLMRerankProvider catch → 降级 |
| LLM 响应超时 | `MODEL_TIMEOUT` (40001) | 同上 |
| LLM 返回非 JSON | `MODEL_NO_RESPONSE` (40002) | 同上 |
| LLM 频率限制 | `MODEL_RATE_LIMIT` (40005) | 同上 |

> 错误码只出现在 `RERANK_DEBUG` 日志的 `error_type` 字段中，用于排查。

---

## 14. 一页速览

| 维度 | 决策 |
|------|------|
| HTTP 契约 | **零变化** — 请求/响应和第一期完全一样 |
| 开关控制 | `.env` 全局 `RERANK_ENABLED`，无请求级开关 |
| 对外感知 | 调用方看不到任何重排痕迹 |
| `top_k` 语义 | 保持 = 最终返回数 |
| `score` | 保持 = 向量原始分 |
| 候选数 | `max(top_k × 3, top_k + 10)` |
| LLM 抽象 | `LLMProvider` ABC（adapters 内部抽象） |
| Domain 端口 | `RerankPort` Protocol（domain/ports.py） |
| LLMProvider 风格 | ABC（含共享 HTTP client 逻辑），与 `EmbedderPort` Protocol 不冲突 |
| 重排实现 | `LLMRerankProvider` 依赖 `LLMProvider`，不直接发 HTTP |
| LLM 并发 | `asyncio.Semaphore`（`LLM_MAX_CONCURRENCY=5`） |
| 降级 | LLM 失败 → 返回向量排序，不中断接口 |
| 缓存命中策略 | 向量余弦相似度 ≥ 0.95 |
| 缓存存储 | 自建 `dict[str, list[CacheEntry]]` + `asyncio.Lock`；每 KB 上限 100 条，TTL 5 分钟 |
| 缓存失效 | KB 文档上传时主动清空（`reranker.clear_cache(kb_id)`）+ TTL 兜底 |
| 缓存部分命中 | Prompt 注入 `reference_scores` 标尺，新 chunk 在相同评分体系下打分 |
| 缓存日志 | `BIZ_EVENT: rerank_cache_hit` + `RERANK_DEBUG` 缓存未命中 |
| 日志 | `retrieve_logs` 表不动；新增 `BIZ_EVENT` + `RERANK_DEBUG` 结构化日志 |
| `log_model_call` | 内部 `_call_api` 桥接，与 embedder 同格式 |
| Domain 模型 | `SearchHit` 不动 |
| 新依赖 | **零** |
| 错误码 | 不新增，复用 40000-40999 |

---

## 15. 推到后续

| 能力 | 状态 |
|------|------|
| 重排结果缓存 | ✅ 已纳入设计（§5.3） |
| 查询改写 | ✅ 已设计（docs/5-query-rewrite-silent-scribe.md），复用 `LLMProvider` |
| 请求级覆盖模型/temperature | 推到后续（有需求时加） |
| Cross-encoder / ColBERT rerank | 架构预留（新增 `RerankPort` 实现即可） |
| 意图识别 | 推到后续（可与 Rewrite 合并为一次 LLM 调用） |
