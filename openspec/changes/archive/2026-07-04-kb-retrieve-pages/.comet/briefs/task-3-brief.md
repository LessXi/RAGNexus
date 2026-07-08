# Task 3: Create KB 链路 — tenant_id 支持

## 依赖
- Task 1 (migration: DB schema 变更)
- Task 2 (models: KnowledgeBase.tenant_id 字段)

## 目标
从 domain port → repository → use case → router，全链路增加 `tenant_id` 支持。

## 文件
- **MOD**: `src/ragnexus/domain/ports.py` — KnowledgeBasePort.create() 签名加 `tenant_id: str`
- **MOD**: `src/ragnexus/adapters/knowledge_base/pg.py` — create() SQL 加 `tenant_id` 列，RETURNING 加 `tenant_id`
- **MOD**: `src/ragnexus/application/create_kb_use_case.py` — execute() 接受 `tenant_id`，校验 1–64 字符
- **MOD**: `src/ragnexus/adapters/http/create_kb_router.py` — 请求体加 `tenant_id`，响应加 `tenant_id`
- **MOD**: `demo_retrieve.py` — create KB 调用加 `tenant_id='default'`

## 具体需求

### 3.1 ports.py
```python
async def create(
    self,
    name: str,
    description: str = "",
    tenant_id: str = "",  # 新增参数
) -> KnowledgeBaseEntity:
```

### 3.2 knowledge_base/pg.py
- `create()` SQL INSERT 加 `tenant_id` 列
- `RETURNING` 子句加 `tenant_id`
- 冲突检测改为 `(tenant_id, name_key)` 联合唯一（与 migration 一致）

### 3.3 create_kb_use_case.py
- `execute()` 接受 `tenant_id: str` 参数
- 校验：1–64 字符，不能为空或纯空白
- 传给 repo.create()

### 3.4 create_kb_router.py
- `_CreateKBRequest` 加 `tenant_id: str = Field(..., min_length=1, max_length=64)`
- 响应 `data` 对象加 `tenant_id`

### 3.5 demo_retrieve.py
- 所有 create KB 调用加 `tenant_id='default'`

## 验证
```bash
pytest tests/unit/application/ -k "create_kb" tests/unit/adapters/test_http_schema_invariance.py -v
```

## 全局约束
- Python 3.11 + FastAPI Clean Architecture
- Factory 模式创建 router
- 中文注释、docstring
- API 响应 `{"code": 0, "data": {...}}`
