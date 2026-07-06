"""DocumentReindexUseCase — 重新索引文档（仅 FAILED 状态允许）。"""

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import DocStatus
from ragnexus.domain.ports import DocumentPort, KnowledgeBasePort
from ragnexus.tasks.indexing import index_document_task


class DocumentReindexUseCase:
    def __init__(self, doc_repo: DocumentPort, kb_repo: KnowledgeBasePort) -> None:
        self._doc_repo = doc_repo
        self._kb_repo = kb_repo

    async def execute(self, doc_id: str, tenant_id: str) -> dict:
        doc = await self._doc_repo.get(doc_id)
        if doc is None:
            raise AppError(ErrorCode.NOT_FOUND, "文档不存在")
        kb = await self._kb_repo.get(doc.kb_id)
        if kb is None or kb.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "文档不存在")
        if doc.status != DocStatus.FAILED:
            raise AppError(
                ErrorCode.RESOURCE_CONFLICT,
                "仅 FAILED 状态的文档允许重新索引",
                errors=[{"field": "status", "reason": f"当前状态: {doc.status.name}"}],
            )
        await self._doc_repo.update_status(
            doc_id, status=DocStatus.PROCESSING, error_message=None
        )
        index_document_task.apply_async(args=[doc_id], ignore_result=True)
        return {"doc_id": doc_id, "status": "processing"}
