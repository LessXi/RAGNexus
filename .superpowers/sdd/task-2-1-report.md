# Task 2.1 — Domain Model 扩展（DocStatus + Document）

## 状态
✅ 已完成

## 修改文件
`src/ragnexus/domain/models.py` — 三步插入：

1. **Line 6**: 添加 `from enum import IntEnum`
2. **Line 9–14**: 添加 `class DocStatus(IntEnum)` 枚举（SUCCESS=1, PROCESSING=2, FAILED=3）
3. **Line 66–80**: 添加 `@dataclass class Document` 领域模型（对应 documents 表完整行）

## 提交
```
341fb315bdc5ab1aae4456b6e47620086b9b1f7d
feat(domain): models.py 新增 Document dataclass + DocStatus IntEnum
```

## 验证输出
```
repr(DocStatus.PROCESSING): <DocStatus.PROCESSING: 2>
value: 2
repr(Document): Document(doc_id='doc1', kb_id='kb1', filename='test.md', file_hash='abc', file_size=100, content_type='text/markdown', content='hello', status=<DocStatus.PROCESSING: 2>, chunk_count=0, error_message=None, uploaded_at=None, updated_at=None)
```

> 注：Python 3.13 的 `IntEnum.__str__` 返回整数值而非枚举名，因此 `print(DocStatus.PROCESSING)` 输出 `2` 而非 `DocStatus.PROCESSING`；`repr()` 正确显示枚举身份，功能验证通过。
