"""DocumentQueryUseCase — 查询单个文档详情。"""

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import Document
from ragnexus.domain.ports import DocumentPort, KnowledgeBasePort


class DocumentQueryUseCase:
    def __init__(self, doc_repo: DocumentPort, kb_repo: KnowledgeBasePort) -> None:
        self._doc_repo = doc_repo
        self._kb_repo = kb_repo

    async def execute(self, doc_id: str, tenant_id: str) -> Document:
        doc = await self._doc_repo.get(doc_id)
        if doc is None:
            raise AppError(ErrorCode.NOT_FOUND, "文档不存在")
        kb = await self._kb_repo.get(doc.kb_id)
        if kb is None or kb.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "文档不存在")
        return doc
