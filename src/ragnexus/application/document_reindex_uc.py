"""DocumentReindexUseCase — 重新索引文档（仅 FAILED 状态允许）。"""

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import DocStatus
from ragnexus.domain.ports import DocumentPort, KnowledgeBasePort
from ragnexus.tasks.indexing import index_document_task


class DocumentReindexUseCase:
    def __init__(
        self,
        doc_repo: DocumentPort,
        kb_repo: KnowledgeBasePort,
        parser_registry=None,  # 新增 — 供 reparse 时获取对应 parser
    ) -> None:
        self._doc_repo = doc_repo
        self._kb_repo = kb_repo
        self._parser_registry = parser_registry  # 新增 — 供 reparse 时获取对应 parser
