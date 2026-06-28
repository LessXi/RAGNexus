# RAGNexus 第二期（续）：查询改写 — 工程规范

> **目标**：在检索链路前增加 LLM 查询改写，优化口语化/模糊查询的向量检索效果。
> - HTTP 契约**零变化**
> - 改写通过 `.env` 全局开关控制，对调用方完全无感知
> - 一次 LLM 调用同时完成"判断是否需要改写"和"执行改写"
> - 复用 `LLMProvider`，不复用 rerank 基础设施
> - 缓存同 rerank 策略（向量相似匹配 + KB 写入失效）

---

## Context

Rerank 优化了检索**结果**的排序质量，但用户的原始 query 本身可能不适合向量检索——口语化、含指代词、过于简短或模糊。Query Rewrite 在 embedding 之前介入，将原始 query 优化为更适合检索的形式。

**与 Rerank 的关系**：Rewrite 和 Rerank 是两个独立的后台优化，串行工作：

```
原始 query → Rewrite → 优化后 query → Embed → Vector Search → Rerank → 返回
```

两者都可独立启用/禁用，互不依赖。

---

## 1. 接口契约

### 1.1 请求/响应 — 零变化

与 Rerank 一致：HTTP 层不做任何改动。调用方不知道 Rewrite 的存在。

---

## 2. 新增文件

```
adapters/
├── rewrite/                           # 查询改写（本期新增）
│   ├── __init__.py
│   └── llm.py                         # LLMRewriteProvider（依赖 LLMProvider）
```

### 修改文件

| 文件 | 改动 |
|------|------|
| `config.py` | 新增 `REWRITE_*` 配置字段 |
| `.env.example` | 同步新增 |
| `domain/ports.py` | 新增 `RewritePort` Protocol |
| `application/retrieve_use_case.py` | 注入 `RewritePort`；在 embed 之前插入 rewrite 步骤 |
| `composition.py` | 创建 `RewriteProvider` 实例，注入 use case |

> `LLMProvider` 已有（Rerank 已引入），Rewrite 直接复用。

---

## 3. Ports

### 3.1 RewritePort

```python
@dataclass
class RewriteResult:
    original_query: str
    rewritten_query: str      # 不需要改写时 = original_query
    needs_rewrite: bool
    reason: str               # 仅日志

class RewritePort(Protocol):
    """查询改写端口。骨架实现: LLMRewriteProvider。"""

    async def rewrite(
        self, *, query: str, kb_ids: list[str]
    ) -> RewriteResult: ...

    async def clear_cache(self, kb_id: str) -> None:
        """清空指定 KB 的改写缓存。文档上传后由 composition.py 调用。"""
        ...
```

---

## 4. Rewrite 数据流

```
POST /v1/rag:retrieve
        │
        ▼
RetrieveUseCase.execute(query, kb_ids, top_k=5)
        │
        ├── 1. validate
        │
        ├── 2. Rewrite:  result = await rewriter.rewrite(query, kb_ids)   ← 新增
        │       │
        │       │  LLMRewriteProvider
        │       │  a) 查缓存（向量相似 ≥ 阈值 0.95）→ 命中直接返回
        │       │  b) LLMProvider.chat_json()  →  判断 + 改写一次完成
        │       │  c) 5 层防御解析  →  降级时返回原始 query
        │       │  d) 写入缓存
        │       │
        │       └── 输出: RewriteResult（query 可能已被改写）
        │
        ├── 3. embedder.embed([result.rewritten_query])
        ├── 4. candidate_k 计算
        ├── 5. store.search_by_vector(...)
        ├── 6. reranker.rerank(...)
        └── 7. return
```

---

## 5. LLM 调用协议

### 5.1 System Prompt

```
你是 RAG 检索查询优化器。分析用户的原始查询，判断是否需要改写为更适合向量检索的形式，如果需要则直接给出改写结果。

判断标准：
- 如果查询包含明确的关键词、名词、专业术语，且语义清晰 → 不需要改写
- 如果查询存在以下问题 → 需要改写：
  · 过于口语化（"上次那个"、"怎么搞的"）
  · 包含指代词（"这个"、"那个"、"它"）
  · 过于简短（缺少关键词）
  · 表述模糊

改写要求：
- 展开缩写和指代，补充隐含的上下文关键词
- 保留用户的核心意图，不要添加用户未提及的信息
- 改写后长度控制在 5-50 字
- 改写结果更适合中文向量检索

只返回 JSON，不要返回 Markdown，不要返回解释性文字。
```

### 5.2 输入 Payload

```json
{
  "query": "上次那个退款的事"
}
```

### 5.3 LLM 返回（需要改写）

```json
{
  "needs_rewrite": true,
  "rewritten_query": "退款政策 申请条件 流程",
  "reason": "包含指代词'上次那个'，缺少具体关键词"
}
```

### 5.4 LLM 返回（不需要改写）

```json
{
  "needs_rewrite": false,
  "rewritten_query": null,
  "reason": "查询已包含具体关键词，语义清晰"
}
```

---

## 6. JSON 解析防御（五层）

| 层级 | 操作 | 失败处理 |
|------|------|---------|
| 0 | API 层 `response_format: json_object` | — |
| 1 | `json.loads(content)` | → Layer 2 |
| 2 | 正则提取 ` ```json ... ``` ` | → Layer 3 |
| 3 | 正则提取最外层 `{...}` | → 降级 |
| 4 | Schema 校验：`needs_rewrite` 存在 + bool 类型；`needs_rewrite=true` 时 `rewritten_query` 非空 | → 降级 |
| 5 | 内容合理性：为空 → 降级；与原始相同 → 降级；> 200 字 → 二次精炼 | → 降级 |

### 二次精炼

`rewritten_query > 200 字` 时，送 LLM 二次精炼：

```
System: "请将以下查询改写结果压缩到 50 字以内，保持核心关键词和语义。只返回 JSON：{"rewritten_query": "..."}"
User:   "<过长的改写结果>"
```

二次精炼仍失败 → 降级为原始 query。

### 降级：任何层失败 → RewriteResult(original_query, original_query, False, reason)

---

## 7. 缓存

与 Rerank 缓存完全相同的策略：

| 参数 | 默认值 |
|------|--------|
| 命中策略 | 向量余弦相似度 ≥ `REWRITE_CACHE_SIMILARITY_THRESHOLD` (0.95) |
| 存储 | 自建 `dict[str, list[CacheEntry]]` + `asyncio.Lock` |
| 每 KB 上限 | `REWRITE_CACHE_MAX_ENTRIES_PER_KB` (100) |
| TTL | `REWRITE_CACHE_TTL_SECONDS` (300s) |
| 失效 | KB 文档上传时 `rewriter.clear_cache(kb_id)` + TTL 兜底 |

> Rewrite 和 Rerank 各自维护独立缓存。不共享（key 空间不同：Rewrite 缓存 `query → rewritten_query`，Rerank 缓存 `query → chunk_score_map`）。

---

## 8. 日志

**改写成功**：

```python
logger.info("", extra={
    "event_type": "BIZ_EVENT",
    "event": "rewrite_completed",
    "kb_ids": kb_ids,
    "original_query": query[:200],
    "rewritten_query": result.rewritten_query[:200],
    "needs_rewrite": True,
    "reason": result.reason,
})
```

**改写降级**：

```python
logger.warning("rewrite 失败，降级为原始 query", extra={
    "event_type": "BIZ_EVENT",
    "event": "rewrite_degraded",
    "kb_ids": kb_ids,
    "query": query[:200],
    "error_type": "ModelTimeout",
    "error_message": "LLM 响应超时",
})
```

**缓存命中**：

```python
logger.info("", extra={
    "event_type": "BIZ_EVENT",
    "event": "rewrite_cache_hit",
    "kb_ids": kb_ids,
    "query": query[:200],
    "similarity": 0.97,
})
```

---

## 9. 配置

```python
# --- Rewrite ---
REWRITE_ENABLED: bool = False
REWRITE_TEMPERATURE: float = 0.0

# --- Rewrite 缓存 ---
REWRITE_CACHE_SIMILARITY_THRESHOLD: float = 0.95
REWRITE_CACHE_MAX_ENTRIES_PER_KB: int = 100
REWRITE_CACHE_TTL_SECONDS: int = 300
```

> `REWRITE_ENABLED=false` 时 composition.py 不创建 RewriteProvider，use case 跳过 rewrite 步骤。

---

## 10. DI 装配

```python
# composition.py

if cfg.REWRITE_ENABLED:
    rewriter = LLMRewriteProvider(
        llm_provider=llm_provider,
        temperature=cfg.REWRITE_TEMPERATURE,
        cache_threshold=cfg.REWRITE_CACHE_SIMILARITY_THRESHOLD,
        cache_max_entries_per_kb=cfg.REWRITE_CACHE_MAX_ENTRIES_PER_KB,
        cache_ttl_seconds=cfg.REWRITE_CACHE_TTL_SECONDS,
    )
else:
    rewriter = NoopRewriteProvider()

retrieve_uc = RetrieveUseCase(
    ...,
    rewriter=rewriter,    # 新增
    reranker=reranker,
    ...
)
```

---

## 11. 一页速览

| 维度 | 决策 |
|------|------|
| HTTP 契约 | **零变化** |
| 开关控制 | `.env` 全局 `REWRITE_ENABLED` |
| 对外感知 | 调用方看不到任何改写痕迹 |
| 改写方式 | 一次 LLM 调用同时判断 + 改写 |
| LLM 复用 | `LLMProvider.chat_json()`（与 rerank 同） |
| 防御 | 5 层（JSON 解析 4 层 + 内容合理性 1 层）；过长结果二次精炼 |
| 降级 | 任何失败 → 返回原始 query，不中断检索 |
| 缓存 | 同 rerank 策略（向量相似 + KB 失效 + TTL） |
| 与 Rerank 关系 | 独立，串行工作（Rewrite → Embed → Rerank） |
| Domain 模型 | `SearchHit` 不动 |
| 新依赖 | **零** |
| 错误码 | 不新增，复用 40000-40999 |

---

## 12. 推到后续

| 能力 | 状态 |
|------|------|
| 意图识别 | 推到后续。可与 Rewrite 合并为一次 LLM 调用（先判断意图 → 如需检索则同时改写）。复用 `LLMProvider` |
| Rewrite 方向引导 | 推到后续。允许调用方在请求中传入`search_direction`提示，引导改写方向 |
| 多 query 变体 | 推到后续。对高难度 query 生成多个改写变体并行检索 |
