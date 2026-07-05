# Task 2.2: UploadResult 增加 status 字段

## 修改内容

### `src/ragnexus/domain/models.py`
- `UploadResult` 新增 `status: DocStatus` 字段（位于 `kb_id` 后、`chunks` 前）
- `chunks: list[Chunk]` 默认值改为 `field(default_factory=list)`，支持不传 chunks 的场景

### `src/ragnexus/application/upload_doc_use_case.py`
- import 行增加 `DocStatus`
- `UploadResult(...)` 调用处增加 `status=DocStatus.SUCCESS`

## 验收结果

```python
>>> from ragnexus.domain.models import UploadResult, DocStatus
>>> r = UploadResult(doc_id='d1', kb_id='k1', status=DocStatus.PROCESSING)
>>> print(r.status)
DocStatus.PROCESSING  # IntEnum value 2
```

```
