"""PgKnowledgeBaseRepository — outbound adapter for KB metadata CRUD.

Implements KnowledgeBasePort over asyncpg.
"""

from nanoid import generate as nanoid_generate

import asyncpg
from domain.errors import ConflictError
from domain.models import KnowledgeBase


class PgKnowledgeBaseRepository:
    """Postgres (asyncpg) adapter for knowledge base metadata."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def create(self, name: str, name_key: str) -> KnowledgeBase:
        """Insert a new knowledge base. Raises ConflictError on name_key duplicate."""
        kb_id = "kb_" + nanoid_generate(size=8)
        try:
            row = await self.pool.fetchrow(
                "INSERT INTO knowledge_bases (id, name, name_key) VALUES ($1, $2, $3) "
                "RETURNING id, name, created_at",
                kb_id, name, name_key,
            )
        except asyncpg.UniqueViolationError:
            raise ConflictError(
                f"知识库名称已存在",
                errors=[{"field": "name", "reason": f"{name!r} 已存在"}],
            )
        return KnowledgeBase(id=row["id"], name=row["name"], created_at=row["created_at"])

    async def get(self, kb_id: str) -> KnowledgeBase | None:
        """Fetch a knowledge base by id, or None."""
        row = await self.pool.fetchrow(
            "SELECT id, name, created_at FROM knowledge_bases WHERE id=$1",
            kb_id,
        )
        return KnowledgeBase(**dict(row)) if row else None

    async def exists(self, kb_id: str) -> bool:
        """Check if a knowledge base exists by id."""
        return bool(await self.pool.fetchval(
            "SELECT 1 FROM knowledge_bases WHERE id=$1",
            kb_id,
        ))

    async def doc_exists(self, doc_id: str) -> bool:
        """Check if a document exists by doc_id."""
        return bool(await self.pool.fetchval(
            "SELECT 1 FROM documents WHERE doc_id=$1",
            doc_id,
        ))
