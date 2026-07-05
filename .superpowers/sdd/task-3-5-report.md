# Task 3.5: purge_document_chunks 报告

## 概述

为关键词检索端口添加 `delete_by_document` 方法，支持按文档 ID 批量删除 ES 中所有关联 chunk。

## 变更文件

| 文件 | 变更 |
|------|------|
| `src/ragnexus/domain/ports.py` | `KeywordSearchPort` 添加 `delete_by_document(doc_id: str) -> None` |
| `src/ragnexus/adapters/keyword_search/elasticsearch.py` | `ESKeywordSearchProvider` 实现 `delete_by_document` |

## 实现细节

### ports.py — KeywordSearchPort

在 `delete` 方法之后新增 Protocol 方法签名：

```python
async def delete_by_document(self, doc_id: str) -> None:
    """从关键词索引删除指定文档的所有 chunk。"""
    ...
```

### elasticsearch.py — ESKeywordSearchProvider

新增方法实现，使用 `delete_by_query` + `term` 查询按 `doc_id` 精确匹配删除：

```python
async def delete_by_document(self, doc_id: str) -> None:
    """按文档 ID 删除 ES 中所有相关 chunk。"""
    try:
        await self._client.delete_by_query(
            index=self.index,
            body={"query": {"term": {"doc_id": doc_id}}},
        )
    except Exception:
        from ragnexus.core.logger import logger
        logger.warning("ES delete_by_document 失败", extra={"doc_id": doc_id})
```

设计要点：
- 异常处理采用 fire-and-forget 模式：捕获所有异常并记录 warning，不中断调用方
- logger 采用局部 import，避免模块级依赖
- 复用已有的 `self._client` 和 `self.index` 属性

## 验收结果

- [x] `KeywordSearchPort.delete_by_document` 存在 → `True`
- [x] `ESKeywordSearchProvider.delete_by_document` 存在 → `True`
- [x] 提交 commit: `4ea6917` — `feat(async): purge_document_chunks — KeywordSearchPort 添加 delete_by_document`
