# Brainstorm Summary

- Change: query-semantic-optimization
- Date: 2026-07-05

## 确认的技术方案

**架构主轴**：删除 `RewriteResult`（4字段），统一用 `QueryProcessResult`（10字段）替代。`RewritePort.rewrite()` 直接返回 `QueryProcessResult`，改写器只填 rewrite 字段，Pipeline 补 synonym 字段。减少一个 dataclass + 一个映射层。

**三层能力叠加**：
1. KB上下文注入：`rewrite()` 新增 `kb_context` 参数（name + description + rewrite_hint），LLM prompt 包含知识库领域信息
2. 词表扩展：`SynonymExpander` 基于 `kb.settings.synonyms` 做精确子串匹配，命中则追加扩展词到 search_query
3. Pipeline串联：`QueryPipeline.process()` 按 enabled 决定是否执行，降级时不阻断检索

**数据存储**：`knowledge_bases.settings` JSONB字段，存 synonyms 和可选 rewrite_hint

**API变更**：请求新增 `query_options`，响应新增 `data.query` + `meta.query_processing`。无处理时 query_processing 为 null

**词表种子**：`generate_synonyms.py` LLM自动提取术语，管理员审核后上传

## 关键取舍与风险

| 取舍 | 决策 |
|------|------|
| 词表开关 | 受 enabled 控制，不开改写也不扩展 |
| 改写模式 | 保留 needs_rewrite 智能判断，不做"总是改写" |
| 多KB上下文 | 取 kb_ids[0] 对应的KB上下文；多KB时LLM只看第一个 |
| query_processing null vs 对象 | 选null（更干净向后兼容），与验收测试文档有意偏离 |
| 词表来源 | 首版人工+LLM生成种子；日志分析/用户反馈后续做 |
| retrieve_logs | 本次不改，后续迭代 |

## 测试策略

- 单元测试：SynonymExpander（6场景）、QueryPipeline（5场景）、改写器字段映射
- 适配测试：7个已有测试文件（RewriteResult → QueryProcessResult）
- 验收测试：11个端到端场景（含降级、跨库隔离、组合链路）
- 任务总数：33个task，12个任务组

## Spec Patch

无。所有spec已覆盖完整验收场景，包括补充的 KB settings CRUD 和 rewrite_latency_ms 哨兵语义。
