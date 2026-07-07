"""PgDocumentRepository 单元测试 — CRUD 操作使用 AsyncMock asyncpg.Pool。"""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from ragnexus.adapters.document.pg import PgDocumentRepository
from ragnexus.domain.models import DocStatus, Document


@pytest.fixture
def mock_pool():
    """返回 AsyncMock 模拟 asyncpg.Pool。"""
    return AsyncMock()


@pytest.fixture
def repo(mock_pool):
    """构造 PgDocumentRepository。"""
    return PgDocumentRepository(pool=mock_pool)


def _row(**kwargs):
    """返回类 dict mock Row。"""
    row = dict(kwargs)

    # 支持 .field 和 ["field"] 两种访问方式
    class MockRow(dict):
        pass

    mr = MockRow(row)
    mr.__dict__ = row
    return mr


# ── get ────────────────────────────────────────────────────────────────


class TestGet:
    """PgDocumentRepository.get() 测试。"""

    @pytest.mark.asyncio
    async def test_get_found(self, repo, mock_pool):
        """存在时返回 Document 领域模型。"""
        now = datetime(2025, 1, 1)
        mock_pool.fetchrow.return_value = _row(
            doc_id="doc_abc",
            kb_id="kb_test",
            filename="test.md",
            file_hash="abc123",
            file_size=1024,
            content_type="text/markdown",
            content="# Title",
            status=1,
            chunk_count=5,
            source_file_path=None,
            source_filename=None,
            error_message=None,
            uploaded_at=now,
            updated_at=now,
        )

        result = await repo.get("doc_abc")

        assert isinstance(result, Document)
        assert result.doc_id == "doc_abc"
        assert result.kb_id == "kb_test"
        assert result.filename == "test.md"
        assert result.status == DocStatus.SUCCESS
        assert result.chunk_count == 5

    @pytest.mark.asyncio
    async def test_get_not_found(self, repo, mock_pool):
        """不存在时返回 None。"""
        mock_pool.fetchrow.return_value = None

        result = await repo.get("doc_gone")

        assert result is None


# ── create ─────────────────────────────────────────────────────────────


class TestCreate:
    """PgDocumentRepository.create() 测试。"""

    @pytest.mark.asyncio
    async def test_create_success(self, repo, mock_pool):
        """插入文档并返回 Document。"""
        result = await repo.create(
            doc_id="doc_new",
            kb_id="kb_test",
            filename="new.md",
            file_hash="def456",
            file_size=512,
            content_type="text/markdown",
            content="# New Doc",
        )

        assert isinstance(result, Document)
        assert result.doc_id == "doc_new"
        assert result.kb_id == "kb_test"
        assert result.filename == "new.md"
        assert result.status == DocStatus.PROCESSING
        assert result.chunk_count == 0
        mock_pool.execute.assert_awaited_once()


# ── update_status ──────────────────────────────────────────────────────


class TestUpdateStatus:
    """PgDocumentRepository.update_status() 测试。"""

    @pytest.mark.asyncio
    async def test_update_to_success(self, repo, mock_pool):
        """更新为 SUCCESS 并设置 chunk_count。"""
        await repo.update_status("doc_abc", status=DocStatus.SUCCESS, chunk_count=3)
        mock_pool.execute.assert_awaited_once()
        sql = mock_pool.execute.call_args.args[0]
        assert "SET status = $1" in sql
        assert "chunk_count" in sql

    @pytest.mark.asyncio
    async def test_update_to_failed_with_error(self, repo, mock_pool):
        """更新为 FAILED 并设置 error_message。"""
        await repo.update_status(
            "doc_abc", status=DocStatus.FAILED, error_message="解析失败"
        )
        mock_pool.execute.assert_awaited_once()
        sql = mock_pool.execute.call_args.args[0]
        assert "SET status = $1" in sql
        assert "error_message" in sql

    @pytest.mark.asyncio
    async def test_update_status_only(self, repo, mock_pool):
        """仅更新 status，不设置 chunk_count 和 error_message。"""
        await repo.update_status("doc_abc", status=DocStatus.PROCESSING)
        mock_pool.execute.assert_awaited_once()
        sql = mock_pool.execute.call_args.args[0]
        assert "chunk_count" not in sql
        assert "error_message" not in sql


# ── delete ─────────────────────────────────────────────────────────────


class TestDelete:
    """PgDocumentRepository.delete() 测试。"""

    @pytest.mark.asyncio
    async def test_delete_executes_sql(self, repo, mock_pool):
        """按 doc_id 删除。"""
        await repo.delete("doc_abc")
        mock_pool.execute.assert_awaited_once_with(
            "DELETE FROM documents WHERE doc_id = $1", "doc_abc"
        )


# ── delete_by_kb ───────────────────────────────────────────────────────


class TestDeleteByKb:
    """PgDocumentRepository.delete_by_kb() 测试。"""

    @pytest.mark.asyncio
    async def test_delete_by_kb_executes_sql(self, repo, mock_pool):
        """按 kb_id 批量删除文档。"""
        await repo.delete_by_kb("kb_test")
        mock_pool.execute.assert_awaited_once_with(
            "DELETE FROM documents WHERE kb_id = $1", "kb_test"
        )


# ── has_processing ─────────────────────────────────────────────────────


class TestHasProcessing:
    """PgDocumentRepository.has_processing() 测试。"""

    @pytest.mark.asyncio
    async def test_has_processing_true(self, repo, mock_pool):
        """存在 PROCESSING 文档时返回 True。"""
        mock_pool.fetchval.return_value = 1

        result = await repo.has_processing("kb_test")

        assert result is True

    @pytest.mark.asyncio
    async def test_has_processing_false(self, repo, mock_pool):
        """不存在 PROCESSING 文档时返回 False。"""
        mock_pool.fetchval.return_value = None

        result = await repo.has_processing("kb_test")

        assert result is False


# ── get_by_kb ──────────────────────────────────────────────────────────


class TestGetByKb:
    """PgDocumentRepository.get_by_kb() 测试。"""

    @pytest.mark.asyncio
    async def test_get_by_kb_returns_list(self, repo, mock_pool):
        """按 kb_id 获取文档列表。"""
        now = datetime(2025, 1, 1)
        mock_pool.fetch.return_value = [
            _row(
                doc_id="doc_1",
                kb_id="kb_test",
                filename="a.md",
                file_hash="h1",
                file_size=100,
                content_type="text/markdown",
                content="# A",
                status=1,
                chunk_count=2,
                source_file_path=None,
                source_filename=None,
                error_message=None,
                uploaded_at=now,
                updated_at=now,
            ),
            _row(
                doc_id="doc_2",
                kb_id="kb_test",
                filename="b.md",
                file_hash="h2",
                file_size=200,
                content_type="text/markdown",
                content="# B",
                status=2,
                chunk_count=0,
                source_file_path=None,
                source_filename=None,
                error_message=None,
                uploaded_at=now,
                updated_at=now,
            ),
        ]

        result = await repo.get_by_kb("kb_test")

        assert len(result) == 2
        assert result[0].doc_id == "doc_1"
        assert result[1].doc_id == "doc_2"
        assert result[1].status == DocStatus.PROCESSING


# ── create with source fields ──────────────────────────────────────────


class TestCreateWithSourceFields:
    """PgDocumentRepository.create() 携带 source_file_path/source_filename 测试。"""

    @pytest.mark.asyncio
    async def test_create_with_source_fields(self, repo, mock_pool):
        """创建文档时传递 source_file_path/source_filename。"""
        result = await repo.create(
            doc_id="doc_src",
            kb_id="kb_test",
            filename="test.md",
            file_hash="abc123",
            file_size=1024,
            content_type="text/markdown",
            content="# Content",
            source_file_path="/data/uploads/test.md",
            source_filename="original.md",
        )

        assert isinstance(result, Document)
        assert result.doc_id == "doc_src"
        assert result.source_file_path == "/data/uploads/test.md"
        assert result.source_filename == "original.md"
        mock_pool.execute.assert_awaited_once()


# ── get returns source fields ─────────────────────────────────────────


class TestGetReturnsSourceFields:
    """PgDocumentRepository.get() 返回 source_file_path/source_filename 测试。"""

    @pytest.mark.asyncio
    async def test_get_returns_source_fields(self, repo, mock_pool):
        """get 返回文档时包含 source_file_path/source_filename。"""
        now = datetime(2025, 1, 1)
        mock_pool.fetchrow.return_value = _row(
            doc_id="doc_src",
            kb_id="kb_test",
            filename="test.md",
            file_hash="abc123",
            file_size=1024,
            content_type="text/markdown",
            content="# Content",
            status=1,
            chunk_count=5,
            source_file_path="/data/uploads/test.md",
            source_filename="original.md",
            error_message=None,
            uploaded_at=now,
            updated_at=now,
        )

        result = await repo.get("doc_src")

        assert isinstance(result, Document)
        assert result.doc_id == "doc_src"
        assert result.source_file_path == "/data/uploads/test.md"
        assert result.source_filename == "original.md"


# ── update_content ─────────────────────────────────────────────────────


class TestUpdateContent:
    """PgDocumentRepository.update_content() 测试。"""

    @pytest.mark.asyncio
    async def test_update_content(self, repo, mock_pool):
        """更新文档 content 字段。"""
        await repo.update_content("doc_abc", "new content")

        mock_pool.execute.assert_awaited_once()
