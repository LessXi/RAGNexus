"""CreateKnowledgeBaseUseCase — validates input and delegates to repo."""

from domain.errors import ValidationError
from domain.models import KnowledgeBase
from domain.ports import KnowledgeBasePort


class CreateKnowledgeBaseUseCase:
    """Create a knowledge base with validated name."""

    def __init__(self, kb_repo: KnowledgeBasePort) -> None:
        self._kb_repo = kb_repo

    async def execute(self, name: str) -> KnowledgeBase:
        name = name.strip()
        if not (1 <= len(name) <= 64):
            raise ValidationError(
                "name 长度必须在 1-64 之间",
                errors=[{"field": "name", "reason": "长度必须在 1-64"}],
            )
        name_key = name.lower()
        return await self._kb_repo.create(name=name, name_key=name_key)
