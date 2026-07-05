"""为 knowledge_bases 表增加 settings JSONB 列，支持知识库配置存储。

settings 列用于存储知识库级别的配置项（如语义相似度阈值、检索策略参数等），
采用 JSONB 类型，默认空对象 '{}'。

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
