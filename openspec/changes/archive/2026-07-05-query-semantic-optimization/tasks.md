## 1. 领域层：删除 RewriteResult，新增 QueryProcessResult

- [x] 1.1 `domain/ports.py`：删除 `RewriteResult` dataclass（4 字段），新增 `QueryProcessResult` dataclass（10 字段：raw_query, effective_query, search_query, needs_rewrite, strategy, rewrite_latency_ms, degraded, degraded_reason, synonym_applied, synonym_expansions）
- [x] 1.2 `domain/ports.py`：`RewritePort.rewrite()` 签名变更：新增 `kb_context: dict | None = None` 参数，返回类型 `RewriteResult` → `QueryProcessResult`
- [x] 1.3 `domain/ports.py`：`KnowledgeBasePort` 增加 `get_settings(kb_id) -> dict` 和 `update_settings(kb_id, settings: dict)` 方法
- [x] 1.4 `domain/models.py`：`KnowledgeBase` 模型增加 `settings: dict` 字段（默认 `{}`）

## 2. Alembic 数据库迁移

- [x] 2.1 创建 migration：`knowledge_bases` 表增加 `settings JSONB NOT NULL DEFAULT '{}'`
- [x] 2.2 `PgKnowledgeBaseRepository` 实现 `get_settings` / `update_settings`，create 时 settings 默认 `{}`
- [x] 2.3 运行 `alembic upgrade head` 验证 migration 成功

## 3. 改写适配器：RewriteResult → QueryProcessResult

- [x] 3.1 `llm.py`：所有 `RewriteResult(...)` 构造替换为 `QueryProcessResult(...)`（15 处：rewrite, _rewrite_impl, _layer5_checks, _check_cache, _write_cache, 5 个降级 return）
- [x] 3.2 `llm.py`：`CacheEntry.rewrite_result` 类型 `RewriteResult` → `QueryProcessResult`
- [x] 3.3 `llm.py`：`_call_llm()` 将 `kb_context`（name + description + rewrite_hint）注入 system prompt
- [x] 3.4 `llm.py`：改写器内部计时，返回 `rewrite_latency_ms`；降级时设置 `degraded=True`，正常时 `degraded=False`
- [x] 3.5 `noop.py`：`RewriteResult(...)` → `QueryProcessResult(...)`，接受 `kb_context` 参数并忽略

## 4. 词表扩展（新增）

- [x] 4.1 新增 `adapters/rewrite/synonym_expander.py`：`SynonymExpander` 类
- [x] 4.2 实现 `expand(effective_query, synonyms) -> (search_query, synonym_applied, expansions)`：中文精确子串匹配 + 英文 casefold + 去重 + 追加
- [x] 4.3 容错：synonyms 格式异常时跳过该组，不抛异常
- [x] 4.4 单元测试 `test_synonym_expander.py`：单组命中、多组命中+去重、未命中、英文大小写、空词表、格式错误容错、跨组扩展词去重

## 5. Pipeline 串联（新增）
- [x] 5.1 新增 `adapters/rewrite/pipeline.py`：`QueryPipeline` 类
- [x] 5.2 实现 `process(raw_query, kb_context, synonyms, enabled) -> QueryProcessResult`：enabled=false→noop; enabled=true→rewrite→expand; rewrite异常→降级
  - `enabled=true` → 调 `rewrite()` → 调 `SynonymExpander.expand()` → 覆盖 search_query 和 synonym 字段
  - `rewrite()` 抛异常 → 捕获，构造 `degraded=true` 的降级结果
  - 多 KB 时取 `kb_ids[0]` 对应的 KB 上下文（name、description、settings）
- [x] 5.3 单元测试 `test_pipeline.py`：改写+扩展同开、仅改写、enabled=false、rewrite 异常降级、rewrite 内部降级透传
## 6. UseCase 和 Router 集成

- [x] 6.1 `retrieve_use_case.py`：不再裸调 `rewriter.rewrite()`，改为调用 `pipeline.process()`；用 `search_query` 做 vector/bm25/hybrid 检索；传 `query_options` 透传
- [x] 6.2 `retrieve_use_case.py`：KB 校验后取出 `name`、`description`、`settings`，组装 `kb_context` 和 `synonyms` 传给 pipeline
- [x] 6.3 `composition.py`：实例化 `QueryPipeline`（注入 rewriter + synonym_expander），传给 use_case
- [x] 6.4 `retrieve_router.py`：`_RetrieveRequest` 增加可选 `_QueryOptions`（enabled: bool, strategy: str）
- [x] 6.5 `retrieve_router.py`：响应 `data` 增加 `query` 字段（返回原始 query）；`meta` 增加可选 `query_processing` 字段（有值或 null）
- [x] 6.6 已有单元测试适配：`test_retrieve.py`、`test_retrieve_hybrid.py` — mock 返回值 `RewriteResult` → `QueryProcessResult`

## 7. 已有测试适配（RewriteResult 引用全部替换）

- [x] 7.1 `test_rewrite_port.py`：完全重写，`RewriteResult` 测试 → `QueryProcessResult` 测试，加 `kb_context` 测试
- [x] 7.2 `test_llm_rewrite.py`：所有 `RewriteResult` 引用 → `QueryProcessResult`，CacheEntry 类型断言更新
- [x] 7.3 `test_noop_rewrite.py`：签名检查更新（返回类型 + kb_context 参数），返回值断言更新
- [x] 7.4 `test_retrieve.py`：fixture mock 返回值字段映射
- [x] 7.5 `test_retrieve_hybrid.py`：同上
- [x] 7.6 `test_retrieve_full_chain.py`：检查并替换所有 `RewriteResult` 引用为 `QueryProcessResult`
- [x] 7.7 `test_es_degradation.py`：同上

## 8. 前端调试台

- [x] 8.1 `types/api.ts`：`RetrieveRequest` 增加 `query_options`，`RetrieveMeta` 增加 `query_processing`
- [x] 8.2 `retrieve.tsx`：检索配置区增加「启用 query 改写」勾选框（含 HelpTooltip："用 AI 把口语问题改成更好搜的说法"）+ `query_options` 传参
- [x] 8.3 `retrieve.tsx`：运行摘要区展示改写前后对比（原话、实际检索句、最终检索句、改写耗时、降级提示、扩展词列表）

## 9. 运维脚本

- [x] 9.1 新增 `scripts/update_kb_settings.py`：`--kb-id` + `--settings-file` 必填，校验 kb_id 存在性，整文件覆盖 settings。打印 kb_id 和 synonyms 组数
- [x] 9.2 新增 `scripts/generate_synonyms.py --kb-id KB_A`：遍历 KB 文档 chunks，调 LLM 提取专业术语并建议同义词，输出 `kb_settings.json`
- [x] 9.3 新增 `examples/kb_settings.example.json`：含 synonyms 和可选 rewrite_hint

## 10. 外部脚本适配

- [x] 10.1 `scripts/show_rewrite_quality.py`：`result.original_query` → `result.raw_query`，`result.rewritten_query` → `result.effective_query`，`result.needs_rewrite` 保留，`result.reason` → `result.degraded_reason`

## 11. 配置与文档

- [x] 11.1 `.env.example` 补充 `QUERY_REWRITE_ENABLED=false` 和 `QUERY_REWRITE_TIMEOUT_MS=2000`
- [x] 11.2 `retrieve_use_case.py` 读取 `QUERY_REWRITE_ENABLED` 环境变量作为全局默认，请求级 `query_options.enabled` 优先

## 12. 验收测试

- [x] 12.1 不传 query_options + 无 settings → 行为与改前一致，`query_processing` 为 null，`data.query` 返回原话
- [x] 12.2 `query_options.enabled=true` + LLM 正常 → `effective_query` 与 `raw_query` 不同，`needs_rewrite=true`
- [x] 12.3 LLM 不可用（API key 错误）→ `degraded=true`，`effective_query==raw_query`，code=0
- [x] 12.4 词表命中 → `synonym_applied=true`，`search_query` 含扩展词
- [x] 12.5 有词表但 query 未命中任何 term → `synonym_applied=false`，`search_query==effective_query`
- [x] 12.6 多组词表同时命中 → 扩展词去重合并
- [x] 12.7 跨库隔离 → KB_A 词表不影响 KB_B
- [x] 12.8 改写+词表同开 → `raw → effective → search_query` 三阶段完整且可不同
- [x] 12.9 KB_B 开改写但无词表 → `effective_query` 有改写，`synonym_applied=false`，`search_query == effective_query`
- [x] 12.10 enabled=false + strategy="rewrite" → enabled 优先，无处理，`query_processing` 为 null
- [x] 12.11 调试台勾选改写 → 运行摘要展示对比；无处理时 `query_processing` 为 null，不展示
