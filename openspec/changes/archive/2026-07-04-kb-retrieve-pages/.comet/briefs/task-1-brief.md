# Task 1: Database Migration

## 目标
创建 Alembic migration `0002_add_tenant_id.py`，给 `knowledge_bases` 表加 `tenant_id` 列，并把 `name_key` 唯一约束改为 `(tenant_id, name_key)` 联合唯一。

## 文件
- **NEW**: `alembic/versions/0002_add_tenant_id.py`
- 不修改其他文件

## 具体需求

### migration upgrade
```sql
ALTER TABLE knowledge_bases ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
```

然后动态查询当前 `name_key` 唯一约束的实际名称（PostgreSQL 自动生成名称不固定），删除它，再建联合唯一：
```sql
DO $$
DECLARE cn text;
BEGIN
  SELECT conname INTO cn FROM pg_constraint
   WHERE conrelid='knowledge_bases'::regclass AND contype='u';
  EXECUTE 'ALTER TABLE knowledge_bases DROP CONSTRAINT ' || cn;
END $$;
ALTER TABLE knowledge_bases ADD UNIQUE (tenant_id, name_key);
```

### migration downgrade
回滚操作：删除 `tenant_id` 列，恢复原来只有 `name_key` 的唯一约束。

## 验证
```bash
alembic upgrade head && alembic downgrade -1
```
确保 upgrade 和 downgrade 都能成功执行。

## 全局约束
- Python 3.11 + FastAPI Clean Architecture
- 中文注释、docstring
- Alembic 标准 migration 格式（参考已有 migration 文件的结构）
- 存量数据全部 `tenant_id='default'`，不影响已有数据
