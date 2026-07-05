# Task 2.4: ports.py 新增 DocumentPort Protocol

## 变更内容

- `src/ragnexus/domain/ports.py`:
  - 导入块新增 `Document`, `DocStatus`（位于 `Chunk` 之后，字母序）
  - 在 `KeywordSearchPort` 之后、`QueryProcessResult` 之前插入 `DocumentPort` Protocol，包含 8 个方法：
    - `get(doc_id) -> Document | None`
    - `create(...) -> Document`
    - `update_status(...) -> None`
    - `delete(doc_id) -> None`
    - `delete_by_kb(kb_id) -> None`
    - `has_processing(kb_id) -> bool`
    - `get_by_kb(kb_id) -> list[Document]`
  - 方法签名中的 `Document`, `DocStatus` 使用字符串引用避免循环导入

## 验证结果

```shell
$ python -c "from ragnexus.domain.ports import DocumentPort; print('DocumentPort imported OK')"
DocumentPort imported OK
```

## 提交

`feat(domain): ports.py 新增 DocumentPort Protocol`
