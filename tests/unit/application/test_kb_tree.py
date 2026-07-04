"""Tests for GetKnowledgeBaseTreeUseCase — 纯委托测试。"""

from unittest.mock import AsyncMock

import pytest

from ragnexus.application.kb_tree_use_case import GetKnowledgeBaseTreeUseCase
from ragnexus.domain.models import DocNode, KBNode, TenantKBTree


@pytest.fixture
def mock_kb_repo():
    """返回一个 AsyncMock KnowledgeBasePort。"""
    return AsyncMock()


@pytest.fixture
def use_case(mock_kb_repo):
    """返回一个 GetKnowledgeBaseTreeUseCase，依赖 mock repo。"""
    return GetKnowledgeBaseTreeUseCase(kb_repo=mock_kb_repo)


def _sample_tree() -> list[TenantKBTree]:
    """构造样例三级树数据用于断言。"""
    return [
        TenantKBTree(
            tenant_id="tenant_a",
            knowledge_bases=[
                KBNode(
                    kb_id="kb_001",
                    name="产品文档",
                    description="",
                    document_count=2,
                    total_chunks=5,
                    created_at="2026-07-01T00:00:00",
                    documents=[
                        DocNode(
                            doc_id="doc_01",
                            filename="README.md",
                            status="completed",
                            uploaded_at="2026-07-02T00:00:00",
                        ),
                        DocNode(
                            doc_id="doc_02",
                            filename="CHANGELOG.md",
                            status="completed",
                            uploaded_at="2026-07-03T00:00:00",
                        ),
                    ],
                ),
            ],
        ),
    ]


@pytest.mark.asyncio
async def test_execute_delegates_to_repo(use_case, mock_kb_repo):
    """无 keyword 时直接委托 repo.list_with_documents() 并返回结果。"""
    expected = _sample_tree()
    mock_kb_repo.list_with_documents.return_value = expected

    result = await use_case.execute()

    assert result is expected
    mock_kb_repo.list_with_documents.assert_awaited_once_with(None)


@pytest.mark.asyncio
async def test_execute_passes_keyword(use_case, mock_kb_repo):
    """有 keyword 时传递給 repo 进行模糊过滤。"""
    expected: list[TenantKBTree] = []
    mock_kb_repo.list_with_documents.return_value = expected

    result = await use_case.execute(keyword="tenant_x")

    assert result is expected
    mock_kb_repo.list_with_documents.assert_awaited_once_with("tenant_x")


@pytest.mark.asyncio
async def test_execute_empty_result(use_case, mock_kb_repo):
    """无匹配数据时返回空列表。"""
    mock_kb_repo.list_with_documents.return_value = []

    result = await use_case.execute()

    assert result == []
    mock_kb_repo.list_with_documents.assert_awaited_once_with(None)
