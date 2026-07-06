"""领域端口（Protocols）— 适配器接口契约。"""

from dataclasses import dataclass
from typing import Protocol

from ragnexus.domain.models import (
    Chunk,
    DocStatus,
    Document,
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
        self, tenant_id: str, keyword: str | None = None
    ) -> list[TenantKBTree]:
        """获取单租户→KB→文档三级树，keyword 模糊匹配 KB 名称。"""
        ...

    async def get_settings(self, kb_id: str) -> dict:
        """获取 KB 的 settings（JSONB）。"""
        ...

    async def update_settings(self, kb_id: str, settings: dict) -> None:
        """更新（覆盖）KB 的 settings。"""
        ...

    async def update(
        self,
        kb_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        settings: dict | None = None,
    ) -> "KnowledgeBase": ...

    async def delete(self, kb_id: str) -> None: ...

    async def has_processing_docs(self, kb_id: str) -> bool:
        """检查知识库下是否有 PROCESSING 状态的文档。"""
        return False


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
        log_id: str = "",
        tenant_id: str = "",
        trace_id: str = "",
        profile: str = "",
        search_query: str = "",
        effective_query: str = "",
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

    async def delete_by_document(self, doc_id: str) -> None:
        """从关键词索引删除指定文档的所有 chunk。"""
        ...


class DocumentPort(Protocol):
    """文档 CRUD 端口 — 从 KnowledgeBasePort 独立出的文档操作。"""

    async def get(self, doc_id: str) -> "Document | None": ...

    async def create(
        self,
        *,
        doc_id: str,
        kb_id: str,
        filename: str,
        file_hash: str,
        file_size: int,
        content_type: str,
        content: str,
    ) -> "Document": ...

    async def update_status(
        self,
        doc_id: str,
        *,
        status: "DocStatus",
        error_message: str | None = None,
        chunk_count: int | None = None,
    ) -> None: ...

    async def delete(self, doc_id: str) -> None: ...

    async def delete_by_kb(self, kb_id: str) -> None: ...

    async def has_processing(self, kb_id: str) -> bool: ...

    async def get_by_kb(self, kb_id: str) -> "list[Document]": ...


@dataclass
class QueryProcessResult:
    """查询处理结果 — 三阶段查询链的输出。

    raw_query → effective_query → search_query
    """

    raw_query: str
    """用户原话，全程不变"""
    effective_query: str
    """LLM 改写后；未改写时 = raw_query"""
    search_query: str
    """追加扩展词后；无扩展时 = effective_query"""
    needs_rewrite: bool
    """LLM 判断是否需要改写"""
    strategy: str
    """"rewrite" | "noop" """
    rewrite_latency_ms: int
    """改写耗时；未改写时 = 0（哨兵值）"""
    degraded: bool
    """改写是否失败降级"""
    degraded_reason: str | None
    """降级原因"""
    synonym_applied: bool
    """词表是否命中"""
    synonym_expansions: list[str]
    """追加的扩展词列表"""


class RewritePort(Protocol):
    """查询改写端口 — 优化口语化/模糊 query 以提升向量检索效果。

    骨架实现: LLMRewriteProvider (启用时), NoopRewriteProvider (禁用时)。
    """

    async def rewrite(
        self,
        *,
        query: str,
        kb_ids: list[str],
        kb_context: dict | None = None,
    ) -> QueryProcessResult:
        """改写查询，返回三段式查询处理结果。

        Args:
            query: 原始用户查询。
            kb_ids: 目标知识库 ID 列表。
            kb_context: 额外上下文字典，包含 KB 的 name、description、settings
                （含 rewrite_hint）。改写器将其注入 system prompt 以提升改写质量。

        Returns:
            QueryProcessResult: raw_query → effective_query → search_query 三段式结构。
        """
        ...

    async def clear_cache(self, kb_id: str) -> None:
        """清空指定 KB 的改写缓存。文档上传后由 composition.py 调用。"""
        ...
