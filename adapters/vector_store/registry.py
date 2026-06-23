"""Vector-store adapter registry."""

from adapters.vector_store.pgvector import PgVectorStore

__all__ = ["PgVectorStore"]
