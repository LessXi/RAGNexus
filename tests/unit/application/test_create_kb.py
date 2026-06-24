"""Tests for CreateKnowledgeBaseUseCase."""

from unittest.mock import AsyncMock

import pytest
from ragnexus.domain.errors import ValidationError, ConflictError
from ragnexus.domain.models import KnowledgeBase

from ragnexus.application.create_kb_use_case import CreateKnowledgeBaseUseCase


@pytest.fixture
def mock_kb_repo():
    """Return an AsyncMock KnowledgeBasePort."""
    return AsyncMock()


@pytest.fixture
def use_case(mock_kb_repo):
    """Return a CreateKnowledgeBaseUseCase with a mocked repo."""
    return CreateKnowledgeBaseUseCase(kb_repo=mock_kb_repo)


@pytest.fixture
def sample_kb():
    """A KnowledgeBase instance for test assertions."""
    from datetime import datetime
    return KnowledgeBase(id="kb_test123", name="Test KB", created_at=datetime.now())


@pytest.mark.asyncio
async def test_create_kb_success(use_case, mock_kb_repo, sample_kb):
    """Valid name should create a KB via the repo and return the domain model."""
    mock_kb_repo.create.return_value = sample_kb

    result = await use_case.execute("  Test KB  ")

    assert result is sample_kb
    mock_kb_repo.create.assert_awaited_once_with(name="Test KB", name_key="test kb")


@pytest.mark.asyncio
async def test_name_too_short(use_case, mock_kb_repo):
    """Empty or whitespace-only name after strip should raise ValidationError."""
    for bad_name in ("", "  "):
        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(bad_name)
        assert exc_info.value.errors[0]["field"] == "name"
    mock_kb_repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_name_too_long(use_case, mock_kb_repo):
    """Name longer than 64 chars after strip should raise ValidationError."""
    long_name = "A" * 65
    with pytest.raises(ValidationError) as exc_info:
        await use_case.execute(long_name)
    assert exc_info.value.errors[0]["field"] == "name"
    mock_kb_repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_name(use_case, mock_kb_repo):
    """When repo.create raises ConflictError, the use case should propagate it."""
    mock_kb_repo.create.side_effect = ConflictError("KB name already exists")

    with pytest.raises(ConflictError):
        await use_case.execute("Duplicate KB")
