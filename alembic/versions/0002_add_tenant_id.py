"""给 knowledge_bases 表添加 tenant_id 列并改唯一约束。

把 name_key 唯一约束改为 (tenant_id, name_key) 联合唯一。
存量数据全部获得 tenant_id='default'。

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. 添加 tenant_id 列，存量数据默认 'default'
    op.execute(
        "ALTER TABLE knowledge_bases "
        "ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"
    )

    # 2. 动态找到 name_key 唯一约束名并删除
    #    PostgreSQL 自动生成名称不固定，必须运行时查询 pg_constraint
    op.execute(
        """
        DO $$
        DECLARE
            cn text;
        BEGIN
            SELECT conname INTO cn
            FROM pg_constraint
            WHERE conrelid = 'knowledge_bases'::regclass
              AND contype = 'u'
              AND pg_get_constraintdef(oid) LIKE 'UNIQUE (%name_key%)';
            EXECUTE 'ALTER TABLE knowledge_bases DROP CONSTRAINT ' || cn;
        END $$;
        """
    )

    # 3. 建联合唯一约束 (tenant_id, name_key)
    op.execute(
        "ALTER TABLE knowledge_bases ADD UNIQUE (tenant_id, name_key)"
    )


def downgrade() -> None:
    # 1. 删除联合唯一约束 (tenant_id, name_key)
    op.execute(
        """
        DO $$
        DECLARE
            cn text;
        BEGIN
            SELECT conname INTO cn
            FROM pg_constraint
            WHERE conrelid = 'knowledge_bases'::regclass
              AND contype = 'u'
              AND pg_get_constraintdef(oid) LIKE 'UNIQUE (%tenant_id%, %name_key%)';
            EXECUTE 'ALTER TABLE knowledge_bases DROP CONSTRAINT ' || cn;
        END $$;
        """
    )

    # 2. 恢复 name_key 唯一约束
    op.execute(
        "ALTER TABLE knowledge_bases ADD UNIQUE (name_key)"
    )

    # 3. 删除 tenant_id 列
    op.execute(
        "ALTER TABLE knowledge_bases DROP COLUMN tenant_id"
    )
