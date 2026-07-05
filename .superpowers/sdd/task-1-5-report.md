# Task 1.5: 更新 schema.sql — 完成报告

**状态**: ✅ 完成

**提交信息**: `docs(db): schema.sql 同步 knowledge_bases + documents 实际表结构`

**提交 Hash**: `29d9779`

## 修改内容

### Step 1: knowledge_bases 表添加缺失列

在 `name_key` 后插入了：
- `tenant_id TEXT NOT NULL DEFAULT ''`
- `description TEXT NOT NULL DEFAULT ''`
- `settings JSONB NOT NULL DEFAULT '{}'::jsonb`

### Step 2: documents 表添加异步索引列

在 `uploaded_at` 后插入了：
- `status INTEGER NOT NULL DEFAULT 2`
- `content TEXT NOT NULL DEFAULT ''`
- `error_message TEXT`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`

## 验证输出

```
✅ knowledge_bases.tenant_id
✅ knowledge_bases.description
✅ knowledge_bases.settings
✅ documents.status
✅ documents.content
✅ documents.error_message
✅ documents.updated_at
All checks passed: True
Found 12 SQL statements
```

文件变更: 1 file, +8 lines, -1 line
