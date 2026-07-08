## Why

当前 `/v1/rag:retrieve` 的 API 虽然已接受 `kb_ids` 列表，但检索执行体仍是"跨库一次查询 + BM25 只查第一个库"的半成品。当用户问题横跨多个知识库时，BM25 结果缺失、跨库 score 不可比，导致融合结果偏向单个库。业务方要么自行调两次接口再手动合并，要么把所有文档混入一个大库，把本应由中台解决的问题推回给接入方。

## What Changes

- **检索管道重构**：`RetrieveUseCase.execute` 改为 per-KB 并行召回（每个库独立 vector + BM25 → 库内 RRF），再跨库 RRF 融合，替代当前的"向量跨库 + BM25 单库"模式
- **跨库 RRF 融合**：在 `domain/retrieval/fusion.py` 新增 `cross_kb_rrf_fuse`，基于 per-KB rank 进行第二层 RRF 融合
- **Plan 配额联动**：Plan 预设新增 `max_kb_per_retrieve` 字段（free=1 / standard=3 / pro=5），替代硬编码的 5 库上限
- **响应体扩展**：chunk 新增 `kb_name` 字段，响应 `data` 返回 `kb_ids`，`meta` 增加多库融合信息（`multi_kb`, `fusion`, `kb_count` 等）
- **前端检索页改造**：单 KB 输入框 → Checkbox 多选（从 Tree API 拉取列表），chunk 卡片增加来源库 Badge
- **eval 适配**：dataset case 支持 `kb_ids` 字段，新增跨库 golden cases，Langfuse 导出脚本适配

## Capabilities

### New Capabilities
- `multi-kb-retrieval`: 多知识库联合检索 — per-KB 并行召回、跨库 RRF 融合、响应 chunk 携带来源库信息

### Modified Capabilities
- `retrieve-api`: API 契约扩展 — 响应 `data` 显式返回 `kb_ids`，`meta` 增加 `multi_kb`/`fusion`/`kb_count` 多库元信息
- `tenant-plans`: Plan 预设新增 `max_kb_per_retrieve` 字段，按套餐分级管控多库检索上限

## Impact

- **后端核心**：`src/ragnexus/application/retrieve_use_case.py`（~100 行重构）、`src/ragnexus/domain/retrieval/fusion.py`（新增跨库 RRF）、`src/ragnexus/domain/models.py`（SearchHit 新增 kb_name）、`src/ragnexus/tenant/plan_presets.py`（新增字段）
- **HTTP 层**：`src/ragnexus/adapters/http/retrieve_router.py`（响应体扩展 + plan 校验）
- **前端**：`admin/src/pages/` 检索页（~150 行）、`admin/src/types/api.ts`（类型定义）
- **eval**：`scripts/run_retrieval_eval.py`、`scripts/export_eval_cases_from_langfuse.py`、新增 `eval/datasets/multi_kb_cases.json`
- **不涉及**：chunking、embedding、parser、文档上传、知识库管理、列表页
