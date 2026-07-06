"""在 retrieve_logs 表新增 6 个字段。

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """添加 log_id / tenant_id / trace_id / profile / search_query / effective_query 列。"""
    for col_name in (
        "log_id",
        "tenant_id",
        "trace_id",
        "profile",
        "search_query",
        "effective_query",
    ):
        op.add_column(
            "retrieve_logs",
            sa.Column(col_name, sa.Text(), nullable=True),
        )


def downgrade() -> None:
    """移除新增列。"""
    for col_name in (
        "effective_query",
        "search_query",
        "profile",
        "trace_id",
        "tenant_id",
        "log_id",
    ):
        op.drop_column("retrieve_logs", col_name)
