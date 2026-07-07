"""add source file fields to documents

为 documents 表新增 source_file_path 和 source_filename 两列。
用于记录文件的上传源路径和原始文件名。

Revision ID: debee218ecdb
Revises: 0008
Create Date: 2026-07-07 23:24:13.632095

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "debee218ecdb"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为 documents 表添加源文件路径和文件名列。"""
    op.add_column("documents", sa.Column("source_file_path", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("source_filename", sa.Text(), nullable=True))


def downgrade() -> None:
    """移除源文件路径和文件名列。"""
    op.drop_column("documents", "source_filename")
    op.drop_column("documents", "source_file_path")
