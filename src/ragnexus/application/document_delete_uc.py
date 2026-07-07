"""DocumentDeleteUseCase — 删除文档。"""

from ragnexus.application.indexing_service import purge_document_chunks
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import DocStatus
from ragnexus.domain.ports import (
    DocumentPort,
    KeywordSearchPort,
    KnowledgeBasePort,
    VectorStorePort,
)


class DocumentDeleteUseCase:
    def __init__(
        self,
        doc_repo: DocumentPort,
        kb_repo: KnowledgeBasePort,
        store: VectorStorePort,
        keyword_store: KeywordSearchPort | None = None,
    ) -> None:
        self._doc_repo = doc_repo
        self._kb_repo = kb_repo
        self._store = store
        self._keyword_store = keyword_store

    async def execute(self, doc_id: str, tenant_id: str) -> None:
        doc = await self._doc_repo.get(doc_id)
        if doc is None:
            raise AppError(ErrorCode.NOT_FOUND, "文档不存在")
        kb = await self._kb_repo.get(doc.kb_id)
        if kb is None or kb.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "文档不存在")
        if doc.status == DocStatus.PROCESSING:
            raise AppError(
                ErrorCode.RESOURCE_CONFLICT,
                "文档正在索引中，无法删除",
                errors=[{"field": "status", "reason": "文档状态为 PROCESSING"}],
            )
        await purge_document_chunks(doc_id, self._store, self._keyword_store)
        await self._doc_repo.delete(doc_id)
