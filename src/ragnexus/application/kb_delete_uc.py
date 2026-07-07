"""KnowledgeBaseDeleteUseCase — 级联删除知识库及其文档、索引。"""

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.ports import (
    DocumentPort,
    KeywordSearchPort,
    KnowledgeBasePort,
    VectorStorePort,
)


class KnowledgeBaseDeleteUseCase:
    """删除知识库：校验租户归属 → 检查处理中文档 → 清关键词索引 → 删文档 → 删 KB。"""

    def __init__(
        self,
        kb_repo: KnowledgeBasePort,
        doc_repo: DocumentPort,
        store: VectorStorePort,
        keyword_store: KeywordSearchPort | None = None,
    ) -> None:
        self._kb_repo = kb_repo
        self._doc_repo = doc_repo
        self._store = store
        self._keyword_store = keyword_store

    async def execute(self, kb_id: str, tenant_id: str) -> None:
        kb = await self._kb_repo.get(kb_id)
        if kb is None or kb.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "知识库不存在")

        if await self._doc_repo.has_processing(kb_id):
            raise AppError(
                ErrorCode.RESOURCE_CONFLICT,
                "知识库下有文档正在索引中，无法删除",
                errors=[{"field": "kb_id", "reason": "存在 PROCESSING 状态的文档"}],
            )

        if self._keyword_store is not None:
            docs = await self._doc_repo.get_by_kb(kb_id)
            for doc in docs:
                try:
                    await self._keyword_store.delete_by_document(doc.doc_id)
                except Exception:
                    pass

        await self._doc_repo.delete_by_kb(kb_id)
        await self._kb_repo.delete(kb_id)
