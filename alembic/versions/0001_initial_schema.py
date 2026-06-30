"""初始数据库 Schema。

基于 docs/sql/schema.sql 的初始迁移。
创建 pgvector 扩展、四张业务表及索引。

Revision ID: 0001
Revises:
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector 扩展
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 知识库表
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name_key"),
    )

    # 文档表
    op.create_table(
        "documents",
        sa.Column("doc_id", sa.Text(), nullable=False),
        sa.Column("kb_id", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("file_hash", sa.Text(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("doc_id"),
    )
    op.create_index("documents_kb_id_idx", "documents", ["kb_id"])
    op.create_index(
        "documents_uploaded_at_idx",
        "documents",
        ["uploaded_at"],
        postgresql_using="btree",
    )

    # Chunk 表：使用 raw SQL 确保 vector(1024) 类型和 HNSW 索引正确
    op.execute(
        """
        CREATE TABLE chunks (
            id          TEXT NOT NULL,
            kb_id       TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
            doc_id      TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
            text        TEXT NOT NULL,
            metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
            embedding   vector(1024) NOT NULL,
            PRIMARY KEY (doc_id, id)
        )
        """
    )
    op.create_index("chunks_kb_id_idx", "chunks", ["kb_id"])
    op.create_index("chunks_doc_id_idx", "chunks", ["doc_id"])
    op.execute(
        "CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # 检索日志表
    op.create_table(
        "retrieve_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kb_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "retrieve_logs_created_at_idx",
        "retrieve_logs",
        ["created_at"],
        postgresql_using="btree",
    )
    op.create_index(
        "retrieve_logs_kb_ids_idx",
        "retrieve_logs",
        ["kb_ids"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    # 逆序删除
    op.drop_table("retrieve_logs")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("knowledge_bases")
    # 不删除 pgvector 扩展（可能被其他用途共享）
