"""空关键词检索提供者 — NoopKeywordSearchProvider。

禁用关键词检索时的直通实现：search_by_keyword 返回空列表，upsert 和 delete 空实现。
"""

from ragnexus.domain.models import Chunk, SearchHit


class NoopKeywordSearchProvider:
    """空关键词检索提供者 — 禁用关键词检索时的直通实现。

    search_by_keyword 始终返回空列表（无关键词索引），
    upsert 和 delete 均为空实现（无副作用）。
    """

    async def search_by_keyword(
        self,
        kb_id: str,
        query: str,
        top_k: int,
    ) -> list[SearchHit]:
        """始终返回空列表 — 无关键词索引可查询。"""
        return []

    async def upsert(self, kb_id: str, chunks: list[Chunk]) -> None:
        """空实现 — 无关键词索引可写入。"""
        pass

    async def delete(self, kb_id: str, chunk_ids: list[str]) -> None:
        """空实现 — 无关键词索引可删除。"""
        pass
