# Brainstorm Summary

- Change: multi-kb-joint-retrieval
- Date: 2026-07-08

## 确认的技术方案

**两阶段 RRF 融合**：per-KB 独立召回（vector+BM25 → 库内 RRF）→ 跨库 RRF 融合。单库和多库统一走新路径（单库时 `asyncio.gather` 单 task + 跨库 RRF 恒等映射）。

**核心流程**：Plan 校验 → KB 校验 → Query 处理一次 → Embedding 一次 → asyncio.gather 各库并行召回 → 库内 RRF → 跨库 RRF → 预加载 kb_name → Rerank 统一执行 → 响应。

**关键参数**：`per_kb_top_k = max(top_k, vector_top_k, 10)`，`rrf_k = 60`（复用），`MULTI_KB_MAX = 5`（硬上限）。

**Plan 联动**：`limits.max_kb_per_retrieve`（free=1 / standard=3 / pro=5），超限返回 `FEATURE_NOT_ALLOWED (20013)`。

**全栈交付**：后端 RRF 重构 + 前端 Checkbox 多选 + eval 适配一次性完成。

## 关键取舍与风险

- **取舍**：统一新路径（非分支隔离）→ 代码更统一，但需充分测试单库等价性
- **风险**：单库路径回归 → 缓解：单库单 task 行为等价 + 充分回归测试
- **风险**：ES BM25 并发压力 → 缓解：已有连接池，2-3 并发远低于上限

## 测试策略

- 单元：`cross_kb_rrf_fuse` 多组/单组退化/rank 均衡；plan 预设值
- E2E：单库兼容、双库融合、plan 拦截（20013）、跨 tenant 隔离、配额计数
- eval：原 dataset 回归分数不降；跨库 golden case context_recall 明显高于单库

## Spec Patch

无。OpenSpec delta spec 已在 open 阶段创建完整（multi-kb-retrieval 新增 + retrieve-api/tenant-plans 修改），本次 brainstorming 未发现需补充的验收场景。
