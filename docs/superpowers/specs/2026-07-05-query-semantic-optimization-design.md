---
comet_change: query-semantic-optimization
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-05-query-semantic-optimization
status: final
---

# 提问语义优化 — 技术设计

## 概述

在 RAGNexus 现有 LLM 改写基础设施上，以"统一用 `QueryProcessResult` 替代 `RewriteResult`"为架构主轴，叠加 KB 上下文注入、词表扩展和三阶段 pipeline，将检索链路升级为 `raw → effective → search_query`。

## 架构

```
src/ragnexus/adapters/rewrite/
├── llm.py                 # MOD: RewriteResult→QueryProcessResult + kb_context注入
├── noop.py                # MOD: 接 kb_context，返回 QueryProcessResult
├── synonym_expander.py    # NEW: SynonymExpander — 词表匹配
├── pipeline.py            # NEW: QueryPipeline — 串联改写+扩展
```

### QueryProcessResult（10字段，替代 RewriteResult）

```python
@dataclass
class QueryProcessResult:
    raw_query: str               # 用户原话，全程不变
    effective_query: str         # LLM改写后；未改写时=raw_query
    search_query: str            # 追加扩展词后；无扩展时=effective_query
    needs_rewrite: bool          # LLM判断是否需要改写
    strategy: str                # "rewrite" | "noop"
    rewrite_latency_ms: int      # 改写耗时；未改写时=0（哨兵值）
    degraded: bool               # 改写是否失败降级
    degraded_reason: str | None  # 降级原因
    synonym_applied: bool        # 词表是否命中
    synonym_expansions: list[str] # 追加的扩展词列表
```

**填充职责**：
| 字段组 | 填充者 |
|--------|--------|
| raw_query, effective_query, needs_rewrite, strategy, rewrite_latency_ms, degraded, degraded_reason | RewritePort.rewrite() |
| search_query, synonym_applied, synonym_expansions | QueryPipeline（覆盖） |

## 数据流

```
POST /v1/rag:retrieve { query, kb_ids, query_options? }
  → retrieve_router: 解析 query_options
  → retrieve_use_case: 查 KB → { name, description, settings }
  → QueryPipeline.process(raw_query, kb_context, synonyms, enabled)
    ├─ [enabled] RewritePort.rewrite(query, kb_ids, kb_context)
    │    → QueryProcessResult (rewrite字段已填)
    ├─ [enabled && synonyms] SynonymExpander.expand(effective_query, synonyms)
    │    → 覆盖 search_query, synonym_applied, synonym_expansions
    └─ 返回完整 QueryProcessResult
  → 用 search_query 做向量/BM25/hybrid检索
  → 响应: { data: { query: raw_query, hits, meta: { query_processing } } }
```

## 关键决策

1. **数据结构统一**：删 RewriteResult，用 QueryProcessResult。改写器直接输出完整结果，Pipeline只补synonym字段
2. **改写模式**：保留 `needs_rewrite` 智能判断（LLM自行决定），不做"总是改写"
3. **词表开关**：受 `enabled` 控制，不开改写也不扩展
4. **多KB上下文**：取 `kb_ids[0]` 的KB上下文（name、description、settings）
5. **降级**：改写失败时 `degraded=true`，`effective_query=raw_query`，检索不挂（code仍为0）
6. **query_processing为null**：不传 query_options 且无 settings 时返回null（与验收测试文档有意偏离，保持向后兼容）

## KB Settings Schema

```json
{
  "synonyms": [
    {"terms": ["背调"], "expand": ["背景调查", "标准问题清单"]},
    {"terms": ["薪酬", "薪资", "工资"], "expand": ["职级", "薪酬定级", "定级标准"]}
  ],
  "rewrite_hint": "可选，补充给LLM的领域说明"
}
```

`knowledge_bases.settings JSONB NOT NULL DEFAULT '{}'`。synonyms和rewrite_hint为独立机制，互不干扰。

## 词表扩展规则

- 遍历 `effective_query` 对每组 synonyms.terms 做中文精确子串匹配（英文casefold）
- 命中组的 expand 词去重后追加到 query 末尾
- 多组同时命中时 expand 去重合并
- 格式异常的 synonyms 静默跳过，不抛异常
- 跨KB隔离：词表仅对当前KB生效

## 词表种子生成

```bash
python scripts/generate_synonyms.py --kb-id KB_A
```

遍历KB文档chunks，调LLM提取专业术语并建议同义词，输出 `kb_settings.json`。管理员审核后通过 `update_kb_settings.py` 上传。输出是草稿而非最终词表——降低从零手写的门槛。

## API变更

**请求**：新增可选 `query_options: { enabled: bool, strategy: "rewrite" }`
**响应**：新增 `data.query`（始终返回原始query）和 `meta.query_processing`（有值或null）
**`enabled`优先于`strategy`**：`enabled=false`时忽略`strategy`

## 变更影响面

| 分类 | 文件数 | 说明 |
|------|--------|------|
| 后端修改 | 8 | ports, llm, noop, pg, retrieve_use_case, composition, retrieve_router, models |
| 后端新增 | 2 | synonym_expander, pipeline |
| 数据迁移 | 1 | alembic: settings JSONB列 |
| 脚本新增 | 2 | update_kb_settings, generate_synonyms |
| 脚本修改 | 1 | show_rewrite_quality |
| 测试适配 | 7 | rewrite_port(重写), llm_rewrite, noop_rewrite, retrieve, retrieve_hybrid, full_chain, es_degradation |
| 测试新增 | 2 | synonym_expander, pipeline |
| 前端 | 2 | types/api.ts, retrieve.tsx |
| 配置/示例 | 2 | .env.example, kb_settings.example.json |

## 测试策略

- **单元测试**：SynonymExpander（单组命中/多组去重/未命中/英文大小写/空词表/格式容错）、QueryPipeline（全开/仅改写/enabled=false/异常降级/内部降级透传）
- **适配测试**：7个已有测试文件的 RewriteResult→QueryProcessResult 字段映射和接口签名
- **验收测试**：11个端到端场景覆盖改前兼容、降级、词表命中/未命中、跨库隔离、组合链路、调试台UI
