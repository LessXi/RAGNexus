"""领域端口（Protocols）— 适配器接口契约。"""

from dataclasses import dataclass
from typing import Protocol

from ragnexus.domain.models import (
    Chunk,
    KnowledgeBase,
    ParsedDocument,
    SearchHit,
    TenantKBTree,
)


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

    async def create(
        self, name: str, name_key: str, tenant_id: str = ""
    ) -> KnowledgeBase: ...

    async def get(self, kb_id: str) -> KnowledgeBase | None: ...

    async def exists(self, kb_id: str) -> bool: ...

    async def doc_exists(self, doc_id: str) -> bool: ...

    async def list_with_documents(
        self, keyword: str | None = None
    ) -> list[TenantKBTree]:
        """获取租户→KB→文档三级树，keyword 模糊匹配 tenant_id。"""
        ...


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
    ) -> list[SearchHit]:
        """对向量召回的候选 chunk 重排序，返回 top_n 结果。

        Args:
            query: 原始查询字符串（未改写），与 BM25 检索和 LLM 看到的 query 一致。
            query_vector: embed(原始 query) 的嵌入向量，用于缓存匹配键。
                注意：不是改写后 query 的向量——缓存必须与原始 query 对齐，
                因为 BM25 和 LLM 都使用原始 query，改写仅用于向量检索阶段。
            kb_ids: 目标知识库 ID 列表。
            chunks: 向量召回返回的候选 chunk 列表。
            top_n: 最终返回的 chunk 数量。

        Returns:
            重排后的 list[SearchHit]，score 保持向量原始分不变。
        """
        ...

    async def clear_cache(self, kb_id: str) -> None:
        """清空指定 KB 的缓存。文档上传后由 composition.py 调用。

        NoopRerankProvider 实现为空。
        """
        ...


class KeywordSearchPort(Protocol):
    """关键词检索端口 — BM25 全文匹配。骨架实现: Elasticsearch。"""

    async def upsert(self, kb_id: str, chunks: list[Chunk]) -> None:
        """将 chunks 写入关键词索引（BM25），同 chunk_id 覆盖。"""
        ...

    async def search_by_keyword(
        self,
        kb_id: str,
        query: str,
        top_k: int,
    ) -> list[SearchHit]:
        """BM25 检索，返回带原始 BM25 score 的 SearchHit。"""
        ...

    async def delete(self, kb_id: str, chunk_ids: list[str]) -> None:
        """从关键词索引删除指定 chunk。"""
        ...


@dataclass
class RewriteResult:
    """查询改写结果。"""

    original_query: str
    rewritten_query: str  # 不需要改写时 = original_query
    needs_rewrite: bool
    reason: str  # 仅日志使用


class RewritePort(Protocol):
    """查询改写端口 — 优化口语化/模糊 query 以提升向量检索效果。

    骨架实现: LLMRewriteProvider (启用时), NoopRewriteProvider (禁用时)。
    """

    async def rewrite(
        self,
        *,
        query: str,
        kb_ids: list[str],
    ) -> RewriteResult: ...

    async def clear_cache(self, kb_id: str) -> None:
        """清空指定 KB 的改写缓存。文档上传后由 composition.py 调用。"""
        ...
