## Why

当前 RAG 检索直接用用户原话做检索，口语化问法与文档专业术语词汇不重合（如"背调要问啥" vs "背景调查标准问题清单"），导致向量检索和关键词检索召回率不佳。虽然项目已有 LLM 改写基础设施（`RewritePort` + `LLMRewriteProvider`），但存在三个关键缺口：(1) 改写时 LLM 不知道知识库领域上下文，(2) 缺乏确定性的术语扩展机制，(3) 改写结果（`RewriteResult`）和未来扩展链路追踪的数据结构不统一，不便叠加新能力。

本次变更以"统一用 `QueryProcessResult` 替代 `RewriteResult`"为架构主轴，在不推翻现有 LLM 改写逻辑的前提下，叠加 KB 上下文注入、词表扩展和三阶段 pipeline，将检索链路升级为 `raw → effective → search_query`。

## What Changes

- **BREAKING**：删除 `RewriteResult` dataclass，统一用 `QueryProcessResult`。`RewritePort.rewrite()` 返回类型变更，所有调用方和测试必须适配
- **BREAKING**：`RewritePort.rewrite()` 接口签名新增 `kb_context: dict | None = None` 参数
- 新增 `SynonymExpander`：基于 KB 级词表的确定性术语扩展，纯规则匹配，不调 LLM
- 新增 `QueryPipeline`：串联改写 + 扩展，填充 `QueryProcessResult` 的 synonym 字段
- `knowledge_bases` 表新增 `settings` JSONB 字段，存储 synonyms 和可选 rewrite_hint
- `POST /v1/rag:retrieve` 请求新增可选 `query_options` 字段，响应新增 `data.query` 和 `meta.query_processing`
- 调试台新增「启用 query 改写」开关和运行摘要中的改写链路对比展示
- 新增 `scripts/update_kb_settings.py` 和 `scripts/generate_synonyms.py`
- LLM 改写 prompt 增加 `kb.name`、`kb.description`、可选 `rewrite_hint` 上下文

## Capabilities

### New Capabilities
- `query-rewrite-enhancement`：用 `QueryProcessResult` 统一改写输出，注入 KB 上下文增强改写精准度
- `synonym-expansion`：基于 KB 级可配置词表的确定性术语扩展
- `query-processing-pipeline`：Pipeline 串联改写和扩展，填充完整的 `QueryProcessResult`

### Modified Capabilities
- `retrieve-api`：请求增加 `query_options`，响应增加 `data.query` 和 `meta.query_processing`

## Impact

- **核心架构**：删除 `domain/ports.py` 中的 `RewriteResult`（4 字段），新增 `QueryProcessResult`（10 字段）。影响 8 个后端文件 + 5-7 个测试文件 + 1 个脚本
- **后端**：`adapters/rewrite/llm.py`（15 处字段映射）、`adapters/rewrite/noop.py`（3 处）、`application/retrieve_use_case.py`（5 处）、`composition.py`（2 处）、`adapters/http/retrieve_router.py`（4 处新增）
- **数据库**：`alembic/` 新增 `settings` JSONB migration
- **前端**：`admin/src/types/api.ts`、`admin/src/pages/retrieve.tsx`
- **新增文件**：`synonym_expander.py`、`pipeline.py`、`update_kb_settings.py`、`generate_synonyms.py`、`kb_settings.example.json`、alembic migration
- **测试**：`test_rewrite_port.py` 完全重写；`test_llm_rewrite.py`、`test_noop_rewrite.py`、`test_retrieve.py`、`test_retrieve_hybrid.py` 适配新接口；新增 `test_synonym_expander.py`、`test_pipeline.py`
