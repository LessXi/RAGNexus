# Task 4: PgDocumentRepository 扩展

## Plan Section

来自 `docs/superpowers/plans/2026-07-07-multi-format-parser.md` Task 4。

### 目标

扩展 PgDocumentRepository 和 DocumentPort 协议，支持新增的 source_file_path/source_filename 字段，新增 update_content 方法。

### 要修改的文件

1. `src/ragnexus/domain/ports.py` — DocumentPort.create 签名扩展 + 新增 update_content
2. `src/ragnexus/adapters/document/pg.py` — create/get/get_by_kb 支持新字段 + 新增 update_content
3. Test: `tests/unit/adapters/test_document_repo.py` — 新增测试

### 变更详述

#### 4.2a: 扩展 DocumentPort.create 签名 (ports.py line 186-195)

当前:
```python
    async def create(
        self,
        *,
        doc_id: str,
        kb_id: str,
        filename: str,
        file_hash: str,
        file_size: int,
        content_type: str,
        content: str,
    ) -> "Document": ...
```

加上 `source_file_path` 和 `source_filename` 可选参数:
```python
    async def create(
        self,
        *,
        doc_id: str,
        kb_id: str,
        filename: str,
        file_hash: str,
        file_size: int,
        content_type: str,
        content: str,
        source_file_path: str | None = None,
        source_filename: str | None = None,
    ) -> "Document": ...
```

#### 4.2b: 新增 DocumentPort.update_content (ports.py, 在 create 之后插入)

```python
    async def update_content(self, doc_id: str, content: str) -> None: ...
```

#### 4.2c: 更新 PgDocumentRepository (pg.py)

##### create 方法 (line 41-72):
- INSERT SQL 增加 `source_file_path, source_filename` 两列，对应 `$8, $9` 参数
- Document 构造增加 `source_file_path=source_file_path, source_filename=source_filename`

当前 INSERT:
```python
"INSERT INTO documents (doc_id, kb_id, filename, file_hash, "
"file_size, content_type, content, status, chunk_count, uploaded_at, updated_at) "
"VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)"
```

改为:
```python
"INSERT INTO documents (doc_id, kb_id, filename, file_hash, "
"file_size, content_type, content, source_file_path, source_filename, "
"status, chunk_count, uploaded_at, updated_at) "
"VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)"
```

参数顺序: doc_id, kb_id, filename, file_hash, file_size, content_type, content, source_file_path, source_filename, DocStatus.PROCESSING.value, 0, now, now

##### get 方法 (line 16-39):
SELECT 增加 `source_file_path, source_filename`，Document 构造增加对应字段。

##### get_by_kb 方法 (line 108-132):
同样增加 SELECT 列和 Document 构造字段。

##### 新增 update_content 方法:
```python
async def update_content(self, doc_id: str, content: str) -> None:
    """更新文档 content 字段 — 供 _prepare_content 延迟解析后回写。"""
    await self.pool.execute(
        "UPDATE documents SET content = $1, updated_at = $2 WHERE doc_id = $3",
        content, datetime.now(UTC), doc_id,
    )
```

### 测试

在 `tests/unit/adapters/test_document_repo.py` 新增:
1. `test_create_with_source_fields` — 验证带新字段的 create 正确
2. `test_get_returns_source_fields` — 验证 get 返回新字段
3. `test_update_content` — 验证 update_content 执行正确 SQL

同时确保所有现有测试通过。

### 测试命令

```bash
pytest tests/unit/adapters/test_document_repo.py -v
```

### Commit

```bash
git add src/ragnexus/adapters/document/pg.py src/ragnexus/domain/ports.py tests/unit/adapters/test_document_repo.py
git commit -m "feat: extend PgDocumentRepository with source file fields and update_content"
```

## 全局约束
- 零破坏
- 新字段保持 nullable（默认 None）
- 中文注释

## 回报要求
1. **状态**: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
2. **RED 证据**: 新测试 FAIL（字段不存在时）
3. **GREEN 证据**: 所有测试 PASS
4. **Commit**: 完整 hash
5. **变更文件 + 顾虑**
