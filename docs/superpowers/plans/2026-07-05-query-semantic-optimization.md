---
change: query-semantic-optimization
design-doc: docs/superpowers/specs/2026-07-05-query-semantic-optimization-design.md
base-ref: 44de6d637db7ca43071f347842c9006b4d8e0894
archived-with: 2026-07-05-query-semantic-optimization
---

# 提问语义优化 — 实施计划

## 总览

34 个任务（12 个阶段 + 11 个验收项）。按依赖拓扑串行执行，同一阶段内可并行。

```
层1（领域）：任务组1         ──▶  无依赖
层2（DB + 适配器）：任务组2-5   ──▶  依赖层1
层3（应用+路由）：任务组6        ──▶  依赖层2
层4（测试适配）：任务组7        ──▶  依赖层3
层5（前端）：任务组8            ──▶  依赖层3（可并行于7）
层6（脚本）：任务组9-10         ──▶  依赖层2
层7（配置+验收）：任务组11-12   ──▶  依赖全部
```

## 阶段 1：领域层变更

**目标**：删除 RewriteResult，新增 QueryProcessResult 和 KB settings 接口

| # | 文件 | 变更 | 预计行数 |
|---|------|------|---------|
| 1.1 | `domain/ports.py` | 删 RewriteResult → 加 QueryProcessResult（10字段） | +30/-10 |
| 1.2 | `domain/ports.py` | RewritePort.rewrite() 签名加 kb_context，返回类型改 | +3/-2 |
| 1.3 | `domain/ports.py` | KnowledgeBasePort 加 get_settings/update_settings | +4 |
| 1.4 | `domain/models.py` | KnowledgeBase 加 settings 字段 | +3 |

**验收**：`test_rewrite_port.py` 适配后通过（阶段 7 执行）

## 阶段 2：Alembic 数据库迁移

**目标**：`knowledge_bases` 表增加 `settings JSONB` 列

| # | 文件 | 变更 | 预计行数 |
|---|------|------|---------|
| 2.1 | `alembic/versions/xxxx.py` | 新增 migration | +20 |
| 2.2 | `adapters/knowledge_base/pg.py` | get_settings / update_settings 实现 | +25 |
| 2.3 | — | `alembic upgrade head` 验证 | — |

**验收**：migration 成功执行，`knowledge_bases` 有 `settings` 列且默认 `{}`

## 阶段 3：改写适配器变更

**目标**：LLMRewriteProvider 和 NoopRewriteProvider 适配新接口

| # | 文件 | 变更 | 预计行数 |
|---|------|------|---------|
| 3.1 | `adapters/rewrite/llm.py` | 15处 RewriteResult→QueryProcessResult | 15处替换 |
| 3.2 | `adapters/rewrite/llm.py` | CacheEntry.rewrite_result 类型改 | +1/-1 |
| 3.3 | `adapters/rewrite/llm.py` | _call_llm 注入 kb_context 到 prompt | +15 |
| 3.4 | `adapters/rewrite/llm.py` | 内部计时 + degraded 标记 | +10 |
| 3.5 | `adapters/rewrite/noop.py` | RewriteResult→QueryProcessResult + kb_context | +5/-5 |

**验收**：`test_llm_rewrite.py` + `test_noop_rewrite.py` 适配后通过

## 阶段 4：词表扩展（新增）

**目标**：SynonymExpander 类

| # | 文件 | 变更 | 预计行数 |
|---|------|------|---------|
| 4.1 | `adapters/rewrite/synonym_expander.py` | 新增 SynonymExpander | +60 |
| 4.4 | `tests/unit/test_synonym_expander.py` | 6场景单元测试 | +80 |

**验收**：`pytest tests/unit/test_synonym_expander.py -v` 全部通过

## 阶段 5：Pipeline 串联（新增）

**目标**：QueryPipeline 串联改写+扩展

| # | 文件 | 变更 | 预计行数 |
|---|------|------|---------|
| 5.1 | `adapters/rewrite/pipeline.py` | 新增 QueryPipeline | +80 |
| 5.3 | `tests/unit/test_pipeline.py` | 5场景单元测试 | +100 |

**验收**：`pytest tests/unit/test_pipeline.py -v` 全部通过

## 阶段 6：UseCase 和 Router 集成

**目标**：检索链路接入 pipeline，API 新增 query_options/query_processing

| # | 文件 | 变更 | 预计行数 |
|---|------|------|---------|
| 6.1 | `application/retrieve_use_case.py` | pipeline.process() 替代裸调 rewrite | +15/-10 |
| 6.2 | `application/retrieve_use_case.py` | KB上下文组装 + synonyms 传递 | +10 |
| 6.3 | `composition.py` | QueryPipeline 依赖注入 | +8 |
| 6.4 | `adapters/http/retrieve_router.py` | _QueryOptions + query_options 字段 | +10 |
| 6.5 | `adapters/http/retrieve_router.py` | data.query + meta.query_processing | +15 |
| 6.6 | `tests/unit/application/test_retrieve.py` | mock 适配 | +10/-10 |

**验收**：`test_retrieve.py` + `test_retrieve_hybrid.py` 适配后通过

## 阶段 7：已有测试适配

**目标**：全测试套件适配 RewriteResult→QueryProcessResult

| # | 文件 | 变更 | 预计行数 |
|---|------|------|---------|
| 7.1 | `tests/unit/test_rewrite_port.py` | 完全重写 | +80/-60 |
| 7.2 | `tests/unit/test_llm_rewrite.py` | 字段映射 + 类型断言 | +20/-20 |
| 7.3 | `tests/unit/test_noop_rewrite.py` | 签名+返回值断言 | +10/-10 |
| 7.4 | `tests/unit/application/test_retrieve.py` | fixture 映射 | +10/-10 |
| 7.5 | `tests/unit/application/test_retrieve_hybrid.py` | fixture 映射 | +10/-10 |
| 7.6 | `tests/integration/test_retrieve_full_chain.py` | RewriteResult→QueryProcessResult | +5/-5 |
| 7.7 | `tests/integration/test_es_degradation.py` | RewriteResult→QueryProcessResult | +5/-5 |

**验收**：`pytest tests/ -x -q` 全部通过

## 阶段 8：前端调试台

**目标**：改写开关 + 运行摘要

| # | 文件 | 变更 | 预计行数 |
|---|------|------|---------|
| 8.1 | `admin/src/types/api.ts` | RetrieveRequest + RetrieveMeta 新字段 | +15 |
| 8.2 | `admin/src/pages/retrieve.tsx` | 改写开关 UI | +20 |
| 8.3 | `admin/src/pages/retrieve.tsx` | 运行摘要展示 | +30 |

**验收**：前端 `npm run build` 通过，调试台勾选改写后摘要正确展示

## 阶段 9：运维脚本

**目标**：词表管理脚本

| # | 文件 | 变更 | 预计行数 |
|---|------|------|---------|
| 9.1 | `scripts/update_kb_settings.py` | 新增 | +40 |
| 9.2 | `scripts/generate_synonyms.py` | 新增 | +80 |
| 9.3 | `examples/kb_settings.example.json` | 新增 | +15 |

**验收**：`python scripts/update_kb_settings.py --help` 正常，example JSON 格式合法

## 阶段 10：外部脚本适配

| # | 文件 | 变更 | 预计行数 |
|---|------|------|---------|
| 10.1 | `scripts/show_rewrite_quality.py` | 字段名映射 | +5/-5 |

**验收**：脚本可正常运行

## 阶段 11：配置与文档

| # | 文件 | 变更 | 预计行数 |
|---|------|------|---------|
| 11.1 | `.env.example` | QUERY_REWRITE_ENABLED + TIMEOUT | +4 |
| 11.2 | `application/retrieve_use_case.py` | 读取环境变量 | +5 |

**验收**：`.env.example` 含新配置项

## 阶段 12：验收测试

11 个端到端场景：不传 query_options、开改写、LLM 降级、词表命中/未命中、多组去重、跨库隔离、组合链路、enabled 优先、调试台 UI。

**验收**：全部场景通过，`query_processing` 行为与 spec 一致。
