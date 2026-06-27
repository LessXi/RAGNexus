"""CreateKnowledgeBaseUseCase — 校验输入并委托给 repo 创建知识库。"""

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.core.logger import logger
from ragnexus.domain.models import KnowledgeBase
from ragnexus.domain.ports import KnowledgeBasePort


class CreateKnowledgeBaseUseCase:
    """创建经过校验的知识库。"""

    def __init__(self, kb_repo: KnowledgeBasePort) -> None:
        self._kb_repo = kb_repo

    async def execute(self, name: str) -> KnowledgeBase:
        name = name.strip()
        if not (1 <= len(name) <= 64):
            raise AppError(
                ErrorCode.PARAM_ERROR,
                "name 长度必须在 1-64 之间",
                errors=[{"field": "name", "reason": "长度必须在 1-64"}],
            )
        name_key = name.lower()
        result = await self._kb_repo.create(name=name, name_key=name_key)

        # BIZ_EVENT: 知识库创建成功（状态转换）
        logger.info(
            "",
            extra={
                "event_type": "BIZ_EVENT",
                "event": "knowledge_base_created",
                "kb_id": result.id,
                "kb_name": result.name,
            },
        )

        return result
