# Task 2.8: composition.py DI 注入 — 报告

**提交**: `1621271` feat(app): composition.py 注入 PgDocumentRepository

## 变更摘要

修改 `src/ragnexus/composition.py`，添加 `PgDocumentRepository` 的导入和实例化，作为占位注入。

### 具体变更

1. **添加导入** (line 45):
   ```python
   from ragnexus.adapters.document.pg import PgDocumentRepository
   ```

2. **添加实例化** (line 389, 在 `kb_repo` 之后):
   ```python
   document_repo = PgDocumentRepository(pool=cast(Any, repo_pool))
   ```

## 验证

- `python -c "from ragnexus.composition import build_app; print('composition imports OK')"` → **通过**，无 ImportError
- 提交成功，+2 行

## 备注

- 这是占位注入，不改变现有行为
- `document_repo` 当前创建后未被使用，将在 Task 3.4（UploadDocumentUseCase 完整重构）中注入到 UseCase
