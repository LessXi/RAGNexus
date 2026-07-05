"""KnowledgeBaseDetailUseCase — 查询单个知识库详情。"""

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import KnowledgeBase
from ragnexus.domain.ports import KnowledgeBasePort


class KnowledgeBaseDetailUseCase:
    """查询知识库详情，校验租户归属。"""

    def __init__(self, kb_repo: KnowledgeBasePort) -> None:
        self._kb_repo = kb_repo

    async def execute(self, kb_id: str, tenant_id: str) -> KnowledgeBase:
        kb = await self._kb_repo.get(kb_id)
        if kb is None or kb.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "知识库不存在")
        return kb
