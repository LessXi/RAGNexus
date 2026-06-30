# Task 6.3-6.4 Report: composition.py 装配 RewriteProvider + upload 缓存清空

## 概述

在 `composition.py` 中完成 RewriteProvider 的 DI 装配，包括：
1. 根据 `REWRITE_ENABLED` 选择 `LLMRewriteProvider` 或 `NoopRewriteProvider`
2. 注入 `rewriter` 到 `RetrieveUseCase`
3. `CacheInvalidatingUploadUseCase` 同时清空 rerank 和 rewrite 缓存

## 变更内容

### 1. 新增导入
- `LLMRewriteProvider` (from `ragnexus.adapters.rewrite.llm`)
- `NoopRewriteProvider` (from `ragnexus.adapters.rewrite.noop`)
- `RewritePort` (from `ragnexus.domain.ports`)
- **修复**: `UploadResult` (from `ragnexus.domain.models`) — 原代码中 `CacheInvalidatingUploadUseCase.execute` 的 `-> UploadResult` 返回类型标注缺少 import，属于先前 commit 的潜在 bug

### 2. CacheInvalidatingUploadUseCase 扩展
- 构造器新增 `rewriter: RewritePort` 参数
- `execute` 方法在 `self._inner.execute(...)` 之后同时调用:
  - `await self._reranker.clear_cache(kb_id)` — 清空重排缓存
  - `await self._rewriter.clear_cache(kb_id)` — 清空查询改写缓存
- 更新 docstring 和注释为"双缓存"

### 3. Rewrite Provider 创建
在 Rerank Provider 创建之后添加：
```python
if cfg.REWRITE_ENABLED:
    rewriter = LLMRewriteProvider(
        llm=llm_provider,
        embedder=embedder,
        cache_similarity_threshold=cfg.REWRITE_CACHE_SIMILARITY_THRESHOLD,
        cache_max_entries=cfg.REWRITE_CACHE_MAX_ENTRIES,
        cache_ttl_seconds=cfg.REWRITE_CACHE_TTL_SECONDS,
        temperature=cfg.REWRITE_TEMPERATURE,
    )
else:
    rewriter = NoopRewriteProvider()
```

### 4. RetrieveUseCase 注入
```python
retrieve_uc = RetrieveUseCase(
    ...,
    rewriter=rewriter,  # 新增
    ...
)
```

### 5. CacheInvalidatingUploadUseCase 包装更新
```python
upload_doc_uc_wrapped = CacheInvalidatingUploadUseCase(upload_doc_uc, reranker, rewriter)
```

## 测试结果

```
pytest: 259 passed, 20 skipped, 1 warning
```

所有 259 个单元测试通过。4 个 wiring 测试修复后通过（之前因 `UploadResult` 缺失 import 导致的 `NameError`）。

## Commit

- `dab1555` — feat(composition): 装配 RewriteProvider + upload 清空双缓存
- 文件: `src/ragnexus/composition.py` (+34 -8)

## 向后兼容

- `REWRITE_ENABLED=False`（默认）时使用 `NoopRewriteProvider`，rewrite 直通，无副作用
- `NoopRewriteProvider.clear_cache` 为空实现
- 不影响现有 Rerank 装配逻辑
