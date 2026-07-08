## 1. 后端核心 — 检索管道重构

- [x] 1.1 新增 `cross_kb_rrf_fuse` 函数到 `src/ragnexus/domain/retrieval/fusion.py`：接受多组 rank-ordered hits，按 `1/(k+rank)` 跨库 RRF 融合，保留原始 kb_id/doc_id/chunk_id
- [x] 1.2 新增 `_retrieve_per_kb` 辅助方法：封装单库召回（vector + BM25 → 库内 RRF），支持 per-KB BM25 降级为纯向量
- [x] 1.3 重构 `RetrieveUseCase.execute` 检索体：per-KB `asyncio.gather` 并行召回 → 跨库 RRF 融合，过滤异常 KB
- [x] 1.4 `SearchHit` dataclass 新增 `kb_name: str` 字段（`domain/models.py`）
- [x] 1.5 预加载 `kb_id → kb_name` 映射（批量 SELECT），跨库 RRF 后逐 chunk 填充
- [x] 1.6 `per_kb_top_k` 配置化：`max(top_k, vector_top_k, bm25_top_k, 10)`
- [x] 1.7 多库词表合并：批量加载所有 KB 的 settings → 去重合并 synonyms → 传给 QueryPipeline
- [x] 1.8 多库改写上下文：LLM 改写 `kb_context` 改为所有 KB 的 name+description 列表

- [x] 2.1 `plan_presets.py` 三档套餐 `limits` 新增 `max_kb_per_retrieve` 字段（free=1, standard=3, pro=5）
- [x] 2.2 `retrieve_router.py` 入口校验：`len(req.kb_ids) <= plan_ctx.limits.max_kb_per_retrieve`，超限返回 `FEATURE_NOT_ALLOWED (20013)`
- [x] 2.3 保留 `MULTI_KB_MAX=5` 硬上限作为天花板

## 3. 响应体扩展

- [x] 3.1 `retrieve_router.py` 响应 `data` 根级新增 `kb_ids` 字段
- [x] 3.2 响应 `meta` 新增多库融合元信息：`multi_kb`, `kb_count`, `per_kb_top_k`, `fusion`, `rrf_k`
- [x] 3.3 `_serialize_hit` 输出 `kb_name` 字段

## 4. 前端 — 检索页改造

- [x] 4.1 检索范围区从单 KB 输入框改为 Checkbox 多选列表（数据源：`GET /v1/knowledge-bases/tree`）
- [x] 4.2 至少勾选一个库才允许提交，否则提示「请选择至少一个知识库」
- [x] 4.3 列表页「去检索」跳转时对应库默认勾选
- [x] 4.4 chunk 卡片增加来源库 Badge（取 `kb_name`，不同颜色区分）
- [x] 4.5 运行摘要区展示联查库数和融合方式
- [x] 4.6 `20013` 错误时展示 plan 限制提示

## 5. Eval & 脚本适配

- [x] 5.1 `scripts/run_retrieval_eval.py` 适配：读 case 时优先 `kb_ids`，回退 `kb_id`
- [x] 5.2 新增 `eval/datasets/multi_kb_cases.json`：2-3 条跨库 golden case
- [x] 5.3 `scripts/export_eval_cases_from_langfuse.py` 适配：优先取 `kb_ids` 字段
- [x] 5.4 `RetrieveRequest` TypeScript 类型更新（如需要新增字段）
- [x] 5.5 `docs/tenant-onboarding.md` 更新：增加 `max_kb_per_retrieve` 说明

## 6. 测试与验收

- [x] 6.1 单元测试：`test_retrieve_use_case` 覆盖单库路径、双库 RRF、多库 plan 拦截
- [x] 6.2 单元测试：`test_fusion` 覆盖 `cross_kb_rrf_fuse` 多组输入、rank 均衡、单组退化
- [x] 6.3 单元测试：`test_plan_presets` 验证 `max_kb_per_retrieve` 各 plan 值
- [x] 6.4 E2E 测试：单库向后兼容（旧 curl 行为不变）
- [x] 6.5 E2E 测试：双库 RRF 融合验证（chunk 带 kb_id/kb_name，meta 多库信息）
- [x] 6.6 E2E 测试：跨 tenant 隔离（混入其他租户库 → NOT_FOUND）
- [x] 6.7 E2E 测试：free plan 拦截（传 2 库 → 20013）
- [x] 6.8 E2E 测试：配额计数验证（双库检索仅计 1 次）
- [x] 6.9 E2E 测试：不存在的库 ID → 整体失败
- [x] 6.10 eval regression：原 `ecommerce_retrieval.json` 单库分数与 baseline 一致
- [x] 6.11 eval 跨库验证：`multi_kb_cases.json` 的 `context_recall` 明显高于单库
