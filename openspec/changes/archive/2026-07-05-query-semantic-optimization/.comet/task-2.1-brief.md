# Task 2.1 实施 Brief

## 任务

创建 Alembic migration：`knowledge_bases` 表增加 `settings JSONB NOT NULL DEFAULT '{}'`

## 当前 schema

`alembic/versions/0001_initial_schema.py` 中 knowledge_bases 表：
- id (Text, PK)
- name (Text)
- name_key (Text, Unique)
- created_at (DateTime TZ, default NOW())

## 变更

创建 `alembic/versions/0004_kb_settings.py`:

1. `down_revision = "0003"`（最新 migration）
2. `revision = "0004"`
3. `upgrade()`: 用 `op.add_column` 给 knowledge_bases 表增加 settings 列
4. `downgrade()`: 用 `op.drop_column` 删除 settings 列

```python
def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "settings",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

def downgrade() -> None:
    op.drop_column("knowledge_bases", "settings")
```

## 约束

- 参考 `0003_tenants_and_api_keys.py` 的文件头格式（docstring、revision、down_revision 等）
- 导入: `from sqlalchemy.dialects import postgresql`
- settings 类型为 JSONB，默认 '{}'
- 创建后运行 `alembic upgrade head` 验证
