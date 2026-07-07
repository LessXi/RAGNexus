"""retrieval_log_observability

为 retrieve_logs 表新增 6 个可观测性列：log_id (UNIQUE)、tenant_id、trace_id、
profile、search_query、effective_query。

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
    """为 retrieve_logs 添加可观测性列。"""
    # 所有列 nullable=True，兼容现有数据
    op.add_column("retrieve_logs", sa.Column("log_id", sa.String(24), nullable=True))
    op.add_column("retrieve_logs", sa.Column("tenant_id", sa.Text(), nullable=True))
    op.add_column("retrieve_logs", sa.Column("trace_id", sa.String(64), nullable=True))
    op.add_column("retrieve_logs", sa.Column("profile", sa.String(32), nullable=True))
    op.add_column("retrieve_logs", sa.Column("search_query", sa.Text(), nullable=True))
    op.add_column(
        "retrieve_logs", sa.Column("effective_query", sa.Text(), nullable=True)
    )

    # log_id 需 UNIQUE 约束，供 feedback API 按 log_id 查找
    op.create_unique_constraint("uq_retrieve_logs_log_id", "retrieve_logs", ["log_id"])


def downgrade() -> None:
    """移除可观测性列，恢复 0007 结构。"""
    op.drop_constraint("uq_retrieve_logs_log_id", "retrieve_logs")
    op.drop_column("retrieve_logs", "effective_query")
    op.drop_column("retrieve_logs", "search_query")
    op.drop_column("retrieve_logs", "profile")
    op.drop_column("retrieve_logs", "trace_id")
    op.drop_column("retrieve_logs", "tenant_id")
    op.drop_column("retrieve_logs", "log_id")
