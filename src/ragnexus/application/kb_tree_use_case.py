"""GetKnowledgeBaseTreeUseCase — 获取单租户下的 KB→文档三级树。"""

from ragnexus.domain.models import TenantKBTree
from ragnexus.domain.ports import KnowledgeBasePort


class GetKnowledgeBaseTreeUseCase:
    """委托 repo.list_with_documents() 获取单租户三级树结构。"""

    def __init__(self, kb_repo: KnowledgeBasePort) -> None:
        self._kb_repo = kb_repo

    async def execute(
        self, tenant_id: str, keyword: str | None = None
    ) -> list[TenantKBTree]:
        """获取三级树，keyword 可选模糊匹配 KB 名称。"""
        return await self._kb_repo.list_with_documents(
            tenant_id=tenant_id, keyword=keyword
        )
