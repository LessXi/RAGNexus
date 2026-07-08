## Why

RAGNexus 检索链路的容错逻辑已在 multi-kb-joint-retrieval 优化中实现（双向 try/except 降级 + `asyncio.gather(return_exceptions=True)` 多库容错），但降级发生在内部，API 响应 metadata 中缺少对应的标记字段。调用方无法区分正常结果、降级结果和空结果——BM25 异常降级为纯向量不告知、多库中某个库失败不告知、chunks=[] 是没索引还是没命中也不告知。这导致「降级了但调用方不知道，空结果和系统错误表现一样」。

索引链路的容错已经完善（Celery 重试 + 事务回滚），检索链路需要补齐对应的容错能力，实现「能降级的尽量降，实在不行才拒绝，并在 metadata 里诚实地标记打了什么折」。

## What Changes

- **Hybrid 双向降级标记完善**：`_retrieve_per_kb` 已实现双向 try/except 降级（vector 失败→BM25，BM25 失败→vector），补充降级时的 metadata 标记（`degraded=true` + `degraded_reason`）
- **多库 partial 容错标记透传**：`execute` 已通过 `asyncio.gather(return_exceptions=True)` 实现单库失败跳过，补充 `failed_kb_ids`、`partial_kb_success` 字段并透传到 API 响应
- **空结果语义区分**：新增 `empty_reason` 字段，区分 `no_indexed_chunks`（无索引 chunk）和 `no_chunks_matched`（有 chunk 但无命中）
- **query 边界校验配置化**：将硬编码的 `QUERY_MAX_LENGTH=2000` 改为环境变量
- **单测覆盖**：新增 `tests/test_retrieve_robustness.py`，覆盖 hybrid 降级、多库容错、query 边界等 7 个场景
- **集成验证脚本**：新增 `scripts/verify_robustness_retrieve.py`，停 ES 后验证降级行为

## Capabilities

### New Capabilities
- `retrieval-robustness`: 检索链路的降级容错与空结果语义区分，包含 metadata 诚实标记

### Modified Capabilities
无——本次改动不改变已有 capability 的 spec 级行为，仅补齐容错路径的 metadata 标记和透传。核心检索逻辑（RRF 融合、rerank、rewrite）保持不变。
