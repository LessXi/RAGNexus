"""创建 tenants 和 api_keys 表，支持多租户架构。

为后续多租户功能奠定基础：
- tenants: 租户基础信息（名称、状态）
- api_keys: API 密钥管理（哈希存储、前缀展示、过期时间）

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 租户表
    op.create_table(
        "tenants",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_tenants_status",
        ),
    )

    # 默认租户：确保至少有一个租户存在，避免 FK 约束失败
    op.execute(
        "INSERT INTO tenants (id, name, status) VALUES ('default', '默认租户', 'active') ON CONFLICT (id) DO NOTHING"
    )

    # 存量数据迁移：确保 knowledge_bases 中所有 tenant_id 都在 tenants 表中
    op.execute(
        """
        INSERT INTO tenants (id, name, status)
        SELECT DISTINCT kb.tenant_id, kb.tenant_id, 'active'
        FROM knowledge_bases kb
        WHERE kb.tenant_id IS NOT NULL
          AND kb.tenant_id != ''
          AND NOT EXISTS (SELECT 1 FROM tenants t WHERE t.id = kb.tenant_id)
        """
    )

    # API 密钥表
    op.create_table(
        "api_keys",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_api_keys_status",
        ),
    )
    op.create_index("idx_api_keys_tenant", "api_keys", ["tenant_id"])

    # 加 FK 约束：knowledge_bases.tenant_id → tenants.id，禁级联删除
    op.create_foreign_key(
        "fk_knowledge_bases_tenant",
        "knowledge_bases",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    # 逆序删除
    op.drop_index("idx_api_keys_tenant", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_constraint(
        "fk_knowledge_bases_tenant", "knowledge_bases", type_="foreignkey"
    )
    op.drop_table("tenants")
