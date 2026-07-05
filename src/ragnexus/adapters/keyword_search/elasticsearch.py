"""ESKeywordSearchProvider — 基于 Elasticsearch BM25 的关键词检索适配器。"""

from __future__ import annotations

from elasticsearch import AsyncElasticsearch
from elasticsearch import exceptions as es_exceptions
from elasticsearch.helpers import async_bulk

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import Chunk, SearchHit

# ============================================================================
# 索引 mapping — 严格按设计文档
# ============================================================================

INDEX_MAPPING: dict = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "kb_id": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            "heading": {"type": "text", "analyzer": "standard"},
            "text": {"type": "text", "analyzer": "standard"},
            "metadata": {"type": "object", "enabled": False},
        }
    },
}


class ESKeywordSearchProvider:
    """Elasticsearch BM25 关键词检索提供者。

    对标 PgVectorStore 的 connect/close 连接管理模式。

    Usage::

        es = ESKeywordSearchProvider(url="http://localhost:9200")
        await es.connect()
        try:
            await es.ensure_index()
            await es.upsert(kb_id, chunks)
            hits = await es.search_by_keyword(kb_id, "search query", top_k=10)
        finally:
            await es.close()
    """

    def __init__(
        self,
        url: str,
        index: str = "ragnexus_chunks",
        request_timeout: float = 10.0,
    ) -> None:
        """初始化 ES 关键词检索提供者。

        Args:
            url: Elasticsearch 连接地址，如 ``http://localhost:9200``
            index: 索引名称，默认 ``ragnexus_chunks``
            request_timeout: 请求超时（秒），默认 10
        """
        self.url = url
        self.index = index
        self.request_timeout = request_timeout
        self._client: AsyncElasticsearch | None = None
        self._connected: bool = False

    # ------------------------------------------------------------------
    # 连接管理（对标 PgVectorStore）
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """创建 AsyncElasticsearch 客户端，建立连接。"""
        self._client = AsyncElasticsearch(
            hosts=[self.url],
            request_timeout=self.request_timeout,
        )
        self._connected = True

    async def close(self) -> None:
        """关闭 ES 客户端连接（如果存在）。"""
        if self._client is not None:
            await self._client.close()
            self._client = None
            self._connected = False

    async def ensure_index(self) -> None:
        """确保索引存在；不存在则按 INDEX_MAPPING 创建。"""
        if self._client is None:
            raise AppError(
                ErrorCode.DB_CONNECTION_ERROR,
                "ES 客户端未连接，请先调用 connect()",
            )
        exists = await self._client.indices.exists(index=self.index)
        if not exists:
            await self._client.indices.create(index=self.index, body=INDEX_MAPPING)

    # ------------------------------------------------------------------
    # 数据操作
    # ------------------------------------------------------------------

    async def upsert(self, kb_id: str, chunks: list[Chunk]) -> None:
        """批量索引 chunks 到 ES，使用 chunk.id 作为文档 _id。

        Args:
            kb_id: 知识库 ID
            chunks: 待索引的 chunk 列表

        Raises:
            AppError: 批量写入失败时抛出 KEYWORD_UPSERT_FAILED
        """
        if self._client is None:
            raise AppError(
                ErrorCode.DB_CONNECTION_ERROR,
                "ES 客户端未连接，请先调用 connect()",
            )

        actions = (
            {
                "_index": self.index,
                "_id": chunk.id,
                "_source": {
                    "chunk_id": chunk.id,
                    "kb_id": kb_id,
                    "doc_id": chunk.doc_id,
                    "heading": chunk.metadata.get("heading", ""),
                    "text": chunk.text,
                    "metadata": chunk.metadata,
                },
            }
            for chunk in chunks
        )

        try:
            await async_bulk(self._client, actions)
        except es_exceptions.TransportError as e:
            raise AppError(
                ErrorCode.KEYWORD_UPSERT_FAILED,
                f"ES bulk 索引失败: {e}",
            ) from e

    async def search_by_keyword(
        self,
        kb_id: str,
        query: str,
        top_k: int,
    ) -> list[SearchHit]:
        """BM25 关键词检索，跨 heading（权重×3）和 text 字段。

        使用 multi_match query + bool.filter 按 kb_id 过滤。

        Args:
            kb_id: 知识库 ID
            query: 检索查询文本
            top_k: 返回的最大命中数

        Returns:
            SearchHit 列表（按 BM25 score 降序），异常时返回空列表
        """
        if self._client is None:
            return []

        body = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["heading^3", "text"],
                            }
                        }
                    ],
                    "filter": [
                        {"term": {"kb_id": kb_id}},
                    ],
                }
            },
            "size": top_k,
        }

        try:
            response = await self._client.search(index=self.index, body=body)
        except es_exceptions.TransportError:
            return []

        hits = response.get("hits", {})
        hit_list = hits.get("hits", [])

        results: list[SearchHit] = []
        for hit in hit_list:
            src: dict = hit.get("_source", {})
            metadata: dict[str, object] = dict(src.get("metadata", {}))
            # 确保 heading 可从 metadata 读取（设计文档：heading 从 _source 取）
            heading = src.get("heading")
            if heading and "heading" not in metadata:
                metadata["heading"] = heading
            results.append(
                SearchHit(
                    chunk_id=src.get("chunk_id", ""),
                    kb_id=src.get("kb_id", kb_id),
                    doc_id=src.get("doc_id", ""),
                    score=hit.get("_score", 0.0),
                    text=src.get("text", ""),
                    metadata=metadata,
                )
            )

        return results

    async def delete(self, kb_id: str, chunk_ids: list[str]) -> None:
        """按 chunk_id 列表删除 ES 文档（同时校验 kb_id）。

        Args:
            kb_id: 知识库 ID
            chunk_ids: 待删除的 chunk_id 列表

        Raises:
            AppError: 删除失败时抛出 KEYWORD_DELETE_FAILED
        """
        if self._client is None:
            raise AppError(
                ErrorCode.DB_CONNECTION_ERROR,
                "ES 客户端未连接，请先调用 connect()",
            )

        if not chunk_ids:
            return

        try:
            await self._client.delete_by_query(
                index=self.index,
                body={
                    "query": {
                        "bool": {
                            "must": [
                                {"terms": {"chunk_id": chunk_ids}},
                                {"term": {"kb_id": kb_id}},
                            ]
                        }
                    }
                },
            )
        except es_exceptions.TransportError as e:
            raise AppError(
                ErrorCode.KEYWORD_DELETE_FAILED,
                f"ES delete_by_query 失败: {e}",
            ) from e

    async def delete_by_document(self, doc_id: str) -> None:
        """按文档 ID 删除 ES 中所有相关 chunk。"""
        try:
            await self._client.delete_by_query(
                index=self.index,
                body={"query": {"term": {"doc_id": doc_id}}},
            )
        except Exception:
            from ragnexus.core.logger import logger

            logger.warning("ES delete_by_document 失败", extra={"doc_id": doc_id})
