# Task 2.6 — PgDocumentRepository

**状态**: ✅ 完成  
**提交**: `7cec612 feat(adapters): 新增 PgDocumentRepository 文档 CRUD 适配器`  
**日期**: 2026-07-05

## 产出

| 文件 | 操作 |
|------|------|
| `src/ragnexus/adapters/document/__init__.py` | 新建 — 包初始化 (25 bytes) |
| `src/ragnexus/adapters/document/pg.py` | 新建 — PgDocumentRepository (~130 行) |

## 实现内容

`PgDocumentRepository` 是对 `DocumentPort` 的 asyncpg 适配器实现，负责 documents 表的全部 CRUD：

| 方法 | 功能 |
|------|------|
| `get(doc_id)` | 按 doc_id 查询单条文档 |
| `create(**fields)` | 插入新文档，默认 status=PROCESSING |
| `update_status(doc_id, *, status, ...)` | 动态更新状态/错误信息/chunk_count |
| `delete(doc_id)` | 按 doc_id 删除 |
| `delete_by_kb(kb_id)` | 按 kb_id 批量删除 |
| `has_processing(kb_id)` | 检查知识库是否有处理中的文档 |
| `get_by_kb(kb_id)` | 按 kb_id 查询全部文档，按上传时间降序 |

## 依赖

- `asyncpg.Pool` — 数据库连接池
- `ragnexus.domain.models.DocStatus` — 文档状态枚举 (Task 2.1)
- `ragnexus.domain.models.Document` — 文档领域模型 (Task 2.1)
- `ragnexus.domain.ports.DocumentPort` — 协议定义 (Task 2.4)

## 验证

```bash
$ uv run python -c "from ragnexus.adapters.document.pg import PgDocumentRepository; print('PgDocumentRepository imported OK')"
PgDocumentRepository imported OK
```
