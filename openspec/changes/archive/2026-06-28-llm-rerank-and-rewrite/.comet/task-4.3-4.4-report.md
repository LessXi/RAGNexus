# Task 4.3-4.4 报告: composition.py DI 装配

**日期**: 2026-06-28
**状态**: ✅ 完成

## 变更概览

在 `composition.py` 生命周期中装配 LLMProvider、RerankProvider 并实现 upload_doc 缓存清空。

## 实现细节

### 1. 新增 `CacheInvalidatingUploadUseCase` 包装类

```python
class CacheInvalidatingUploadUseCase:
    """包装 UploadDocumentUseCase，成功后清空 rerank 缓存。"""
```

- 对 `UploadDocumentUseCase` 零侵入
- 构造器接受 `inner: UploadDocumentUseCase` 和 `reranker: RerankPort`
- `execute` 调用 inner 后自动 `await self._reranker.clear_cache(kb_id)`
- `NoopRerankProvider.clear_cache` 为空实现，禁用重排时无副作用

### 2. LLM + Rerank Provider 装配

```python
llm_provider = OpenAICompatibleLLMProvider(
    base_url=cfg.LLM_BASE_URL,
    api_key=cfg.LLM_API_KEY,
    model=cfg.LLM_MODEL,
    max_concurrency=cfg.LLM_MAX_CONCURRENCY,
    max_retries=cfg.LLM_MAX_RETRIES,
    request_timeout=cfg.LLM_REQUEST_TIMEOUT,
    connect_timeout=cfg.LLM_CONNECT_TIMEOUT,
    retry_backoff_base=cfg.LLM_RETRY_BACKOFF_BASE,
)

if cfg.RERANK_ENABLED:
    reranker = LLMRerankProvider(llm=llm_provider, ...)
    candidate_multiplier = cfg.RERANK_CANDIDATE_MULTIPLIER
    min_candidates = cfg.RERANK_MIN_CANDIDATES
else:
    reranker = NoopRerankProvider()
    candidate_multiplier = 1
    min_candidates = 0
```

### 3. RetrieveUseCase 注入

```python
retrieve_uc = RetrieveUseCase(
    kb_repo=kb_repo,
    embedder=embedder,
    store=store,
    log_port=log_repo,
    reranker=reranker,              # 新增
    candidate_multiplier=candidate_multiplier,  # 新增
    min_candidates=min_candidates,  # 新增
)
```

### 4. upload_doc_uc 包装

```python
upload_doc_uc_wrapped = CacheInvalidatingUploadUseCase(upload_doc_uc, reranker)
app.include_router(create_upload_doc_router(upload_doc_uc_wrapped))
```

### 5. app.state 引用

```python
app.state.retrieve_uc = retrieve_uc
app.state.upload_doc_uc = upload_doc_uc_wrapped
```

## 新增 imports

```python
from ragnexus.adapters.llm.openai_compatible import OpenAICompatibleLLMProvider
from ragnexus.adapters.rerank.llm import LLMRerankProvider
from ragnexus.adapters.rerank.noop import NoopRerankProvider
from ragnexus.domain.ports import RerankPort
```

## TDD 测试

新增 `TestRerankLLMWiring` 测试类（tests/unit/adapters/test_middleware.py）：

| 测试 | 状态 |
|------|------|
| `test_rerank_disabled_uses_noop_reranker` | ✅ PASS |
| `test_rerank_enabled_uses_llm_reranker` | ✅ PASS |
| `test_upload_doc_is_wrapped_with_cache_invalidator` | ✅ PASS |

修复 `TestLoggedPoolWiring` 兼容性（添加 `OpenAICompatibleLLMProvider` mock 和 `RERANK_ENABLED=False`）。

## 验证

```bash
uv run pyright src/ragnexus/composition.py  # 0 errors
uv run pytest tests/ -v --ignore=tests/e2e  # 224 passed, 20 skipped
```

## 变更文件

- `src/ragnexus/composition.py` — 主变更
- `tests/unit/adapters/test_middleware.py` — 新增 TDD 测试 + 兼容修复
