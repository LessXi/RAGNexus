# Task 6: Tree API（新增）

## 依赖
- Task 1 (migration: DB 有 tenant_id 列)
- Task 3 (create KB 支持 tenant_id)

## 目标
新建 `GET /v1/knowledge-bases/tree` 端点，返回租户→KB→文档三级树。
## 文件
- **MOD**: `src/ragnexus/domain/ports.py` — KnowledgeBasePort 加 `list_with_documents`
- **MOD**: `src/ragnexus/adapters/knowledge_base/pg.py` — 实现 JOIN 查询
- **NEW**: `src/ragnexus/application/kb_tree_use_case.py` — GetKnowledgeBaseTreeUseCase
- **NEW**: `src/ragnexus/adapters/http/kb_tree_router.py` — GET /v1/knowledge-bases/tree
- **MOD**: `src/ragnexus/composition.py` — 注册新 router + use case

## 具体需求

### 6.1 ports.py
```python
async def list_with_documents(self, keyword: str | None = None) -> list[TenantKBTree]:
    """获取租户→KB→文档三级树，keyword 模糊匹配 tenant_id。"""
    ...
```

### 6.2 knowledge_base/pg.py
```sql
SELECT kb.tenant_id, kb.id AS kb_id, kb.name, kb.description, kb.created_at,
       d.id AS doc_id, d.filename, d.status, d.uploaded_at
FROM knowledge_bases kb
LEFT JOIN documents d ON d.kb_id = kb.id
WHERE ($1::text IS NULL OR kb.tenant_id ILIKE '%' || $1 || '%')
ORDER BY kb.tenant_id, kb.created_at DESC, d.uploaded_at DESC
```
在 Python 层组装为 `list[TenantKBTree]`（使用 Task 2 定义的类型）。

### 6.3 kb_tree_use_case.py
```python
class GetKnowledgeBaseTreeUseCase:
    def __init__(self, kb_repo: KnowledgeBasePort):
        self._kb_repo = kb_repo

    async def execute(self, keyword: str | None = None) -> list[TenantKBTree]:
        return await self._kb_repo.list_with_documents(keyword)
```

### 6.4 kb_tree_router.py
- Factory 模式：`def create_kb_tree_router(use_case: GetKnowledgeBaseTreeUseCase) -> APIRouter`
- `GET /v1/knowledge-bases/tree?keyword=xxx`
- 响应: `{"code": 0, "data": [TenantKBTree, ...]}`

### 6.5 composition.py
- 注册 `GetKnowledgeBaseTreeUseCase`（依赖 `pg_kb_repo`）
- 注册 `kb_tree_router`

## 验证
```bash
curl -s http://localhost:8000/v1/knowledge-bases/tree | python -m json.tool
```

## 全局约束
- Python 3.11 + FastAPI Clean Architecture
- Factory 模式创建 router
- 中文注释、docstring
- API 响应 `{"code": 0, "data": {...}}`
