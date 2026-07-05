# Task 1.4: Alembic Migration — document_status

## 状态

✅ **完成**

## 提交

- **Hash**: `931d4de`
- **Message**: `feat(db): Alembic migration — documents 表增加 status/content/error_message/updated_at`

## 迁移内容

### 新增列

| 列名 | 类型 | 可空 | 默认值 |
|------|------|------|--------|
| `status` | `INTEGER` | NO | `2` |
| `content` | `TEXT` | NO | `''` |
| `error_message` | `TEXT` | YES | `NULL` |
| `updated_at` | `TIMESTAMPTZ` | NO | `NOW()` |

### Revision Chain

```
0005 (kb_description) → 0006 (document_status)
```

- `upgrade`: 0005 → 0006 ✅
- `downgrade`: 0006 → 0005 ✅
- `re-upgrade`: 0005 → 0006 ✅

## 验证命令输出

### alembic upgrade head

```
INFO  [alembic.runtime.migration] Running upgrade 0005 -> 0006, document_status
```

### alembic downgrade 0005

```
INFO  [alembic.runtime.migration] Running downgrade 0006 -> 0005, document_status
```

### 列名校验 (information_schema)

```
status               integer                   nullable=NO  default=2
content              text                      nullable=NO  default=''::text
error_message        text                      nullable=YES default=None
updated_at           timestamp with time zone  nullable=NO  default=now()
```

### alembic_version

```
0006
```

## 备注

- 迁移使用原始 SQL (`op.execute()`) 配合 `IF NOT EXISTS` / `IF EXISTS`，幂等安全
- 迁移 `0005_kb_description` 因其 `description` 列已存在（非 Alembic 方式添加），执行前需要 `alembic stamp 0005` 跳过
