## ADDED Requirements

### Requirement: 数据库迁移管理

系统 SHALL 使用 Alembic 管理数据库 Schema 的版本化迁移，替代手动执行 schema.sql。

#### Scenario: 初始迁移
- **WHEN** 运行 `alembic upgrade head`
- **THEN** 数据库中创建 `alembic_version` 表，所有 schema.sql 中的表（knowledge_bases、documents、chunks、retrieve_logs）以及 pgvector extension、HNSW 索引被创建

#### Scenario: 迁移可回滚
- **WHEN** 运行 `alembic downgrade -1`
- **THEN** schema 回退到上一个版本，数据不丢失（降级脚本不删除用户数据表，仅撤销结构性变更）

#### Scenario: 自动迁移
- **WHEN** 应用启动时检测到未执行的迁移
- **THEN** 应用打印警告日志 `WARNING: N pending migration(s). Run 'alembic upgrade head' before deploying`

### Requirement: 迁移脚本生成

系统 SHALL 支持基于当前模型定义自动生成迁移脚本。

#### Scenario: 自动生成
- **WHEN** 开发者修改了模型定义后运行 `alembic revision --autogenerate -m "<描述>"`
- **THEN** 生成包含正确 UPGRADE 和 DOWNGRADE 操作的迁移脚本

## REMOVED Requirements

<!-- 无 -->
