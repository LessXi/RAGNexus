# 批次4审查报告：Task 4.1-4.4（thorough）— Rerank 链路集成

> 审查模式：thorough（最多 2 轮审查-修复）
> 审查范围：3 个提交（NoopRerankProvider 截断修复 + RetrieveUseCase rerank 集成 + composition.py DI 装配）
> 审查日期：2026-06-28
> 审查依据：spec.md / design.md / docs/4-llm-rerank-silent-judge.md（第 5、8、9 节）

---

## 审查提交

| 提交 | 标题 | 改动文件 |
|------|------|----------|
| `5067aba` | fix(rerank): NoopRerankProvider 按 top_n 截断 | noop.py, test_noop_rerank.py |
| `17986a5` | feat(retrieve): RetrieveUseCase 注入 RerankPort + 插入 rerank 步骤 | retrieve_use_case.py, test_retrieve.py |
| `4c69af7` | feat(composition): 装配 LLMProvider + RerankProvider + upload 缓存清空 | composition.py, test_middleware.py |

---

## 1. Spec Compliance（规格合规）

### 判定：✅ 通过

逐项验证结果（基于源码实读，非依赖 diff 描述）：

| # | 检查项 | 状态 | 证据 |
|---|--------|------|------|
| 1 | RetrieveUseCase 构造器新增 `reranker, candidate_multiplier, min_candidates` | ✅ | `retrieve_use_case.py:28-30`，`reranker: RerankPort` 为必选参数 |
| 2 | `candidate_k = max(top_k * candidate_multiplier, top_k + min_candidates)` | ✅ | `retrieve_use_case.py:65-68`，公式与 spec 完全一致 |
| 3 | execute() 在向量召回后、返回前插入 rerank | ✅ | 召回 `:71` → rerank `:74-80` → return `:82`，顺序正确 |
| 4 | 禁用重排时 `candidate_k = top_k`（multiplier=1, min=0） | ✅ | `composition.py:194-195` Noop 分支硬编码 1/0；测试 `test_retrieve_success` 断言 `candidate_k == top_k` |
| 5 | composition.py 根据 RERANK_ENABLED 选择 LLM/Noop | ✅ | `composition.py:180-195` if/else 分支 |
| 6 | LLMProvider 构造参数与 config LLM_* 字段对应 | ✅ | `composition.py:168-177`，7 个 LLM_* 字段全部映射 |
| 7 | LLMRerankProvider 构造参数与 config RERANK_* 字段对应 | ✅ | `composition.py:181-188`，6 个 RERANK_* 字段全部映射（所有已存在的字段） |
| 8 | upload_doc 成功后调 `reranker.clear_cache(kb_id)` | ✅ | `composition.py:54-61` CacheInvalidatingUploadUseCase 包装类 |
| 9 | NoopRerankProvider.clear_cache 空实现 | ✅ | `noop.py:28-30` `pass` |
| 10 | score 字段保持向量原始分 | ✅ | `LLMRerankProvider._merge_and_sort` 仅按 rerank_score 排序，不修改 `chunk.score`；Noop 直接切片返回 |
| 11 | HTTP 契约零变化（router 未修改） | ✅ | `git log` 确认 retrieve_router.py 本批次零改动；models.py/errors.py 零改动 |

**关键正确性验证**：
- `candidate_k` 公式：spec 要求 `max(top_k × multiplier, top_k + min)`，实现 `max(top_k * self._candidate_multiplier, top_k + self._min_candidates)` — 一致
- 禁用直通：Noop 分支 `candidate_multiplier=1, min_candidates=0` → `max(top_k*1, top_k+0) = top_k` — 正确，无额外召回
- rerank 插入位置：向量召回 → rerank → return，符合 spec §5 数据流

---

## 2. Code Quality（代码质量）

### 判定：Approved（1 个 MINOR）

#### 2.1 类型注解完整性

| 项 | 状态 | 说明 |
|----|------|------|
| `RetrieveUseCase.__init__` 参数注解 | ✅ | `reranker: RerankPort`, `candidate_multiplier: int`, `min_candidates: int` |
| `RetrieveUseCase.execute` 返回注解 | ✅ | `-> list[SearchHit]` |
| `CacheInvalidatingUploadUseCase.__init__` | ✅ | `inner: UploadDocumentUseCase`, `reranker: RerankPort` |
| `CacheInvalidatingUploadUseCase.execute` **返回注解缺失** | ⚠️ MINOR | `async def execute(self, ...) -> UploadResult:` 缺少 `-> UploadResult`；对比 `UploadDocumentUseCase.execute` 有 `-> UploadResult` |

#### 2.2 docstring 完整性（中文）

| 文件 | 状态 |
|------|------|
| `noop.py` | ✅ 类 docstring + 方法 docstring 均为中文，描述了截断语义 |
| `retrieve_use_case.py` | ✅ 关键步骤有中文行内注释（候选数计算、向量召回、重排） |
| `composition.py` | ✅ `CacheInvalidatingUploadUseCase` 有中文类 docstring，说明零侵入设计和 Noop 无副作用 |

#### 2.3 测试覆盖

运行 `uv run pytest tests/unit/application/test_retrieve.py tests/unit/test_noop_rerank.py tests/unit/adapters/test_middleware.py -q` → **34 passed**。

| 维度 | 覆盖 | 测试用例 |
|------|------|----------|
| rerank 集成 | ✅ | `test_rerank_called_with_correct_kwargs`, `test_rerank_result_is_returned`, `test_noop_rerank_integration` |
| candidate_k 计算 | ✅ | `test_candidate_k_uses_multiplier`, `test_candidate_k_uses_min_candidates`, `test_candidate_k_takes_max`（三种取 max 场景全覆盖）|
| DI 装配 | ✅ | `test_rerank_disabled_uses_noop_reranker`, `test_rerank_enabled_uses_llm_reranker`, `test_upload_doc_is_wrapped_with_cache_invalidator` |
| 缓存清空包装 | ✅ | `test_upload_doc_is_wrapped_with_cache_invalidator` 验证类型 + app.state 注入 |
| Noop 截断修复 | ✅ | `test_rerank_truncates_to_top_n`, `test_rerank_returns_same_chunks_no_modification` |

#### 2.4 TDD 证据

- `test_noop_rerank.py` 顶部注释 `TDD: RED → GREEN`
- `test_middleware.py` `TestRerankLLMWiring` 类注释 `RED → ... GREEN → lifespan 创建 LLMProvider + RerankProvider`
- 测试先于实现验证协议（`test_satisfies_rerank_port_protocol` 用 inspect 验证签名）

#### 2.5 CacheInvalidatingUploadUseCase 包装类设计

✅ **优秀**。对 `UploadDocumentUseCase` 零侵入：
- 包装类持有 `inner: UploadDocumentUseCase` 引用，不修改原类
- `execute` 调用 `inner.execute` 后追加 `clear_cache`，失败语义：inner 抛异常时 clear_cache 不执行（异常传播，符合"成功后清空"语义）
- 禁用时包装 `NoopRerankProvider`，`clear_cache` 空实现无副作用 — docstring 明确说明
- composition.py 注入包装类到 router（`:229`），原 use case 不暴露给路由

#### 2.6 错误处理

- ✅ rerank 失败降级在 `LLMRerankProvider` 内部（`llm.py:273-288` catch + 返回原始排序），不传播到 use case — 符合 spec D3
- ✅ `CacheInvalidatingUploadUseCase` 未吞 inner 异常（clear_cache 仅在 inner 成功后执行）

#### 2.7 资源管理

- ✅ lifespan 的 finally 块清理顺序未受影响（rerank/llm 实例无显式 close 需求，httpx client 随进程退出）

---

## 3. 信息性观察（非阻塞）

### 3.1 [批次1遗留] `RERANK_CACHE_PREVIEW_MAX_CHARS` config 字段缺失

- **现象**：spec.md §6.2 + docs/4 §5.3/§10.1 均定义了 `RERANK_CACHE_PREVIEW_MAX_CHARS`（content_preview 截断长度，默认 150）。但 `config.py` 未定义此字段，`composition.py:181-188` 装配 `LLMRerankProvider` 时也未传 `cache_preview_max_chars`，依赖构造器默认值 150。
- **影响**：用户无法通过 `.env` 调整 content_preview 截断长度，固定 150。功能可用（默认值正确），仅可配置性缺失。
- **责任归属**：**批次1（config 字段定义）**，非本批。本批职责"LLMRerankProvider 构造参数与 config RERANK_* 字段对应" 100% 满足——composition 映射了所有已存在的 `RERANK_*` 字段。
- **建议**：在批次1 补充 `RERANK_CACHE_PREVIEW_MAX_CHARS: int = 150` 到 config.py，并在 composition.py 传参。

### 3.2 [信息性] DI 测试未断言构造 kwarg 映射

- **现象**：`TestRerankLLMWiring` 的 3 个测试用 `patch("ragnexus.composition.OpenAICompatibleLLMProvider")` 整体替换类，仅验证"调用了构造器"和"reranker 类型分支"，未断言 `LLM_*` / `RERANK_*` 字段到构造 kwarg 的具体映射关系。
- **影响**：如果 composition 把 `cfg.LLM_API_KEY` 错传成 `cfg.LLM_MODEL`，测试不会发现。
- **性质**：pre-existing 测试风格（`TestLoggedPoolWiring` 同模式），非本批引入。
- **建议**：可后续增强为 `assert_mock_called_with` 断言具体 kwarg，但不阻塞本批。

### 3.3 [信息性] config 字段命名与 spec 微调

- spec/docs 用 `RERANK_CACHE_MAX_ENTRIES_PER_KB`，实现用 `RERANK_CACHE_MAX_ENTRIES`。内部一致（config/llm.py/composition 全用短名），属可接受命名调整。

---

## 4. 总结

### 审查结论：✅ 通过

**Spec Compliance**：✅ 全部 11 项检查通过。rerank 链路集成完整正确——构造器注入、candidate_k 公式、rerank 插入位置、禁用直通、DI 装配分支、缓存清空包装、score 语义保持、HTTP 契约零变化均符合规格。

**Code Quality**：Approved。测试 34 个全通过，TDD 证据充分，CacheInvalidatingUploadUseCase 零侵入包装设计良好。

### 需要修复的问题清单

| 级别 | 问题 | 责任批次 | 阻塞本批？ |
|------|------|----------|-----------|
| MINOR | `CacheInvalidatingUploadUseCase.execute` 缺 `-> UploadResult` 返回类型注解（与 `UploadDocumentUseCase.execute` 风格不一致） | 本批 | 否 |
| IMPORTANT | `RERANK_CACHE_PREVIEW_MAX_CHARS` config 字段缺失（spec 定义但 config.py 未实现） | 批次1 | 否 |

**建议**：
1. 本批可合入。MINOR 返回类型注解建议顺手补上（一行改动）。
2. 批次1 遗留的 `RERANK_CACHE_PREVIEW_MAX_CHARS` 在对应批次补齐。

---

## 验证证据

- 测试运行：`uv run pytest ... -q` → 34 passed, 1 warning（starlette deprecation，pre-existing）
- git 确认：retrieve_router.py / models.py / errors.py 本批次零改动
- 源码实读：retrieve_use_case.py / composition.py / noop.py / llm.py / ports.py / config.py / upload_doc_use_case.py / upload_doc_router.py
- 规格对照：spec.md 7 个 Requirement + docs/4 §5/§8/§9 + design.md Decisions
