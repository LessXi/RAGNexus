# Task 2.4

## Requirements

### 2.4 retrieval_logs 表扩展
- **目标**: Alembic migration 0008 新增 6 列 + schema.sql 同步
- **文件**: `alembic/versions/0008_retrieval_log_observability.py`, `docs/sql/schema.sql`
- **要点**: log_id VARCHAR(24) UNIQUE, tenant_id TEXT, trace_id VARCHAR(64), profile VARCHAR(32), search_query TEXT, effective_query TEXT；均可空；tenant_id 从 TenantContext 获取，供 feedback 校验租户归属
- **依赖**: 1.0（Alembic 就绪）
- **验证**: `alembic upgrade head` 成功，`\\d retrieve_logs` 显示 6 个新列
- **预估**: 20min


## TDD
写测试先于实现。RED → GREEN → 提交。