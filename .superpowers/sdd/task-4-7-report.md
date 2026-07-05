# Task 4.7 — 路由注册 + tree 适配 (补充)

**Date**: 2026-07-05
**Status**: ✅ 完成

## 变更摘要

### 1. 注册 document_router 和 kb_router 到 FastAPI app

**文件**: `src/ragnexus/composition.py`

- **命名冲突解决**: 原有 `create_kb_router` (创建 KB) 重命名为 `create_kb_create_router`，避免与新的 `create_kb_router` (KB 运维) 冲突
- 新增 9 个导入：
  - `DocumentQueryUseCase`, `DocumentDeleteUseCase`, `DocumentReindexUseCase`
  - `KnowledgeBaseDetailUseCase`, `KnowledgeBaseUpdateUseCase`, `KnowledgeBaseDeleteUseCase`
  - `create_document_router`, `create_kb_router`
- 在 `lifespan()` 的 try 块中构造 6 个 use case 实例
- 注册 2 个新 router 到 app

### 2. tree 接口适配异步索引状态

**文件**: `src/ragnexus/adapters/knowledge_base/pg.py`

- SQL 查询新增 `d.status` 和 `d.error_message` 列
- DocNode 构造使用 `_status_map = {1: "success", 2: "processing", 3: "failed"}` 映射状态
- 传递 `error_message=row.get("error_message")`

**文件**: `src/ragnexus/adapters/http/kb_tree_router.py`

- `_tree_to_dict` 序列化新增 `"error_message": d.error_message`

## 验证结果

```
✓ All imports OK
✓ DocNode fields: {'doc_id', 'uploaded_at', 'error_message', 'filename', 'status'}
✓ DocNode has status and error_message ✓
✓ build_app() succeeds without errors
```

## 涉及文件

| 文件 | 变更类型 |
|------|---------|
| `src/ragnexus/composition.py` | 添加导入、use case 构造、router 注册 |
| `src/ragnexus/adapters/knowledge_base/pg.py` | SQL 添加 status/error_message 列，DocNode 状态映射 |
| `src/ragnexus/adapters/http/kb_tree_router.py` | `_tree_to_dict` 添加 error_message 字段 |
