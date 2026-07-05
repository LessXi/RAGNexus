"""KnowledgeBaseUpdateUseCase — 更新知识库名称、描述或配置。"""

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import KnowledgeBase
from ragnexus.domain.ports import KnowledgeBasePort


class KnowledgeBaseUpdateUseCase:
    """部分更新知识库元数据，校验租户归属和 settings 类型。"""

    def __init__(self, kb_repo: KnowledgeBasePort) -> None:
        self._kb_repo = kb_repo

    async def execute(
        self,
        kb_id: str,
        tenant_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        settings: dict | None = None,
    ) -> KnowledgeBase:
        kb = await self._kb_repo.get(kb_id)
        if kb is None or kb.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "知识库不存在")
        if settings is not None and not isinstance(settings, dict):
            raise AppError(ErrorCode.PARAM_ERROR, "settings 必须是 JSON 对象")
        return await self._kb_repo.update(
            kb_id, name=name, description=description, settings=settings
        )
