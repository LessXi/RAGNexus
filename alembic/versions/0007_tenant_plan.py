"""添加 tenants.plan 列，支持租户分级。

为非 demo 租户设置 'standard'，tenant_demo 设置为 'pro'。

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """添加 plan 列并迁移已有租户数据。"""
    # 1. 添加 plan 列，server_default='free' 确保非空约束通过
    op.add_column(
        "tenants",
        sa.Column(
            "plan",
            sa.String(32),
            nullable=False,
            server_default="free",
        ),
    )

    # 2. 迁移已有租户：非 demo → standard，demo → pro
    op.execute("UPDATE tenants SET plan = 'standard' WHERE id NOT IN ('demo')")
    op.execute("UPDATE tenants SET plan = 'pro' WHERE id = 'demo'")

    # 3. 移除 server_default，改为应用层控制默认值
    op.alter_column("tenants", "plan", server_default=None)


def downgrade() -> None:
    """移除 plan 列。"""
    op.drop_column("tenants", "plan")
