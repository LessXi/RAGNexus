# Task 2.3 实施 Brief

## 任务

运行 `alembic upgrade head` 验证 migration 成功执行

## 步骤

```bash
cd /path/to/project
alembic upgrade head
```

## 验证

- 命令成功执行，无错误
- `knowledge_bases` 表有 `settings` 列
- 现有行的 settings 为 `{}`
- 验证命令: `alembic current` 显示 `0004`

## 约束

- 必须先完成 Task 2.1（migration 文件创建）
- 需要数据库连接可用（检查 .env 中的 DATABASE_URL）
