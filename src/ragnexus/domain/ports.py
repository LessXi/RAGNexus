"""领域端口（Protocols）— 适配器接口契约。"""

from typing import Protocol

from ragnexus.domain.models import Chunk, KnowledgeBase, ParsedDocument, SearchHit


class VectorStorePort(Protocol):
    """向量存储 + 检索。骨架实现: pgvector。"""

    async def upsert(self, kb_id: str, chunks: list[Chunk]) -> None: ...

    async def search_by_vector(
        self,
        query_vector: list[float],
        top_k: int,
        kb_ids: list[str],
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

    async def parse(self, content: bytes, filename: str) -> ParsedDocument: ...


class RetrieveLogPort(Protocol):
    """retrieve 日志（fire-and-forget）。骨架实现: PgRetrieveLogRepository。"""

    async def log(
        self,
        *,
        query: str,
        kb_ids: list[str],
        top_k: int,
        hit_count: int,
        latency_ms: int,
    ) -> None: ...


class RerankPort(Protocol):
    """重排端口 — 对向量召回候选 chunk 重排序。

    骨架实现: LLMRerankProvider (启用时), NoopRerankProvider (禁用时)。
    返回类型为 list[SearchHit] — 排好序，score 保持向量原始分不变。
    """

    async def rerank(
        self,
        *,
        query: str,
        query_vector: list[float],
        kb_ids: list[str],
        chunks: list[SearchHit],
        top_n: int,
    ) -> list[SearchHit]: ...

    async def clear_cache(self, kb_id: str) -> None:
        """清空指定 KB 的缓存。文档上传后由 composition.py 调用。

        NoopRerankProvider 实现为空。
        """
        ...
