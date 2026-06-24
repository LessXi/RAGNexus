"""Domain ports (Protocols) — interface contracts for adapters."""

from typing import Protocol

from ragnexus.domain.models import KnowledgeBase, Chunk, SearchHit, ParsedDocument


class VectorStorePort(Protocol):
    """向量存储 + 检索。骨架实现: pgvector。"""

    async def upsert(self, kb_id: str, chunks: list[Chunk]) -> None: ...

    async def search_by_vector(
        self, query_vector: list[float], top_k: int, kb_ids: list[str],
    ) -> list[SearchHit]: ...


class KnowledgeBasePort(Protocol):
    """KB 元数据 CRUD。骨架实现: PgKnowledgeBaseRepository。"""

    async def create(self, name: str, name_key: str) -> KnowledgeBase: ...

    async def get(self, kb_id: str) -> KnowledgeBase | None: ...

    async def exists(self, kb_id: str) -> bool: ...

    async def doc_exists(self, doc_id: str) -> bool: ...


class EmbedderPort(Protocol):
    """文本 → 向量。骨架实现: OpenAICompatEmbedder。"""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class ParserPort(Protocol):
    """文档解析。骨架实现: MarkdownAndTextParser。"""

    def parse(self, content: bytes, filename: str) -> ParsedDocument: ...


class RetrieveLogPort(Protocol):
    """retrieve 日志（fire-and-forget）。骨架实现: PgRetrieveLogRepository。"""

    async def log(
        self, *, query: str, kb_ids: list[str], top_k: int,
        hit_count: int, latency_ms: int,
    ) -> None: ...
