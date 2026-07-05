# Task 3.6: SynonymSyncUploadUseCase 触发时机调整

## 变更

**文件**: `src/ragnexus/composition.py`

### 1. 增加 DocStatus 导入

```python
from ragnexus.domain.models import DocStatus, UploadResult
```

### 2. 词表同步触发条件修改

**修改前**: Upload 完成后无条件触发词表同步（只要 LLM 可用）。

**修改后**: 仅在 `result.status == DocStatus.SUCCESS` 时触发词表同步。

```python
# 异步索引模式：仅在同步成功时触发词表同步
# (Worker 进程独立于 API 进程，词表同步将在 IndexingService.execute SUCCESS 后触发)
if result.status == DocStatus.SUCCESS:
    if self._llm is not None:
        import asyncio as _asyncio
        _asyncio.create_task(self._sync_synonyms(kb_id))
        # ... logger.info ...
```

### 影响

- 异步索引模式下 `result.status` 始终为 `PROCESSING`，不会触发词表同步
- 词表同步的实际触发将在后续 Task 中在 `IndexingService` 内部实现
- 不影响同步成功时的正常同步行为
