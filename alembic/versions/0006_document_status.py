"""document_status — 添加 status/content/error_message/updated_at 列

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为 documents 表添加异步索引所需列。"""
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS status INTEGER NOT NULL DEFAULT 2"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content TEXT NOT NULL DEFAULT ''"
    )
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS error_message TEXT")
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
    )


def downgrade() -> None:
    """移除异步索引相关列。"""
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS content")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS error_message")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS updated_at")
