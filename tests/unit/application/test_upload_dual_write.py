"""UploadDocumentUseCase 双写 (PG + ES) 4 状态矩阵测试。

覆盖:
- test_both_succeed:   ES 成功 + PG 成功 → commit
- test_both_fail:      ES 失败 + PG 失败 → rollback
- test_pg_ok_es_fail:  PG 成功 ES 失败 → rollback PG + raise ES error
- test_pg_fail_es_ok:  PG 失败 ES 成功 → delete ES orphan + raise PG error
"""

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from ragnexus.application.upload_doc_use_case import UploadDocumentUseCase
from ragnexus.domain.models import UploadResult


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_kb_repo():
    repo = MagicMock()
    repo.exists = AsyncMock(return_value=True)
    repo.doc_exists = AsyncMock(return_value=False)
    return repo


@pytest.fixture
def mock_parser():
    parser = MagicMock()
    parser.parse = AsyncMock(
        return_value=MagicMock(
            sections=[MagicMock(heading="Intro", level=1, content="Hello world")],
            raw_text="Hello world",
        )
    )
    return parser


@pytest.fixture
def mock_embedder():
    emb = MagicMock()
    emb.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    return emb


@pytest.fixture
def mock_pg_store():
    """Mock PgVectorStore — 暴露内部事务方法供双写使用。"""
    import asyncpg

    store = MagicMock()
    # 便捷 upsert（es_enabled=False 时用）
    store.upsert = AsyncMock()
    # 事务方法（es_enabled=True 时用）
    conn = MagicMock(spec=asyncpg.Connection)
    conn.execute = AsyncMock()
    store.acquire_connection = AsyncMock(return_value=conn)
    store._upsert_in_transaction = AsyncMock()
    store.pool = MagicMock()
    store.pool.release = AsyncMock()
    return store


@pytest.fixture
def mock_keyword_store():
    """Mock KeywordSearchPort (ES)。"""
    store = MagicMock()
    store.upsert = AsyncMock()
    store.delete = AsyncMock()
    return store


@pytest.fixture
def test_file_bytes():
    return b"# Hello\n\nThis is a test document."


@pytest.fixture
def expected_doc_id(test_file_bytes):
    return "doc_" + hashlib.sha256(test_file_bytes).hexdigest()[:16]


@pytest.fixture
def use_case(mock_kb_repo, mock_embedder, mock_parser, mock_pg_store):
    """双写启用时: es_enabled=True 且注入 keyword_store。"""
    from ragnexus.domain.chunking import heading_aware_split

    return UploadDocumentUseCase(
        kb_repo=mock_kb_repo,
        parser=mock_parser,
        embedder=mock_embedder,
        chunker=heading_aware_split,
        store=mock_pg_store,
        keyword_store=None,
        es_enabled=False,
    )


# ---------------------------------------------------------------------------
# helper
# ---------------------------------------------------------------------------


def _make_dual_write_use_case(
    mock_kb_repo, mock_embedder, mock_parser, mock_pg_store, mock_keyword_store
):
    """创建双写启用的 use case。"""
    from ragnexus.domain.chunking import heading_aware_split

    return UploadDocumentUseCase(
        kb_repo=mock_kb_repo,
        parser=mock_parser,
        embedder=mock_embedder,
        chunker=heading_aware_split,
        store=mock_pg_store,
        keyword_store=mock_keyword_store,
        es_enabled=True,
    )


# ---------------------------------------------------------------------------
# 4 状态矩阵测试（es_enabled=True）
# ---------------------------------------------------------------------------


class TestUploadDualWrite:
    """双写 (PG + ES) 状态矩阵测试集。"""

    @pytest.mark.asyncio
    async def test_both_succeed(
        self,
        mock_kb_repo,
        mock_embedder,
        mock_parser,
        mock_pg_store,
        mock_keyword_store,
        test_file_bytes,
        expected_doc_id,
    ):
        """ES 成功 + PG 成功 → commit PG, 返回 UploadResult。"""
        uc = _make_dual_write_use_case(
            mock_kb_repo,
            mock_embedder,
            mock_parser,
            mock_pg_store,
            mock_keyword_store,
        )

        result = await uc.execute(
            kb_id="kb_test123",
            file_content=test_file_bytes,
            filename="test.md",
            content_type="text/markdown",
        )

        # 返回成功
        assert isinstance(result, UploadResult)
        assert result.doc_id == expected_doc_id

        # acquire_connection 被调用
        conn = mock_pg_store.acquire_connection.return_value
        mock_pg_store.acquire_connection.assert_awaited_once()

        # ES upsert 被调用
        mock_keyword_store.upsert.assert_awaited_once()
        es_call_kb_id = mock_keyword_store.upsert.call_args[0][0]
        assert es_call_kb_id == "kb_test123"

        # PG _upsert_in_transaction 被调用
        mock_pg_store._upsert_in_transaction.assert_awaited_once_with(
            conn,
            "kb_test123",
            result.chunks,
        )

        # commit
        conn.execute.assert_awaited_with("COMMIT")

        # pool.release 被调用
        mock_pg_store.pool.release.assert_awaited_once_with(conn)

        # 快捷 upsert 不应被调用
        mock_pg_store.upsert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_both_fail(
        self,
        mock_kb_repo,
        mock_embedder,
        mock_parser,
        mock_pg_store,
        mock_keyword_store,
        test_file_bytes,
    ):
        """ES 失败 + PG 失败 → rollback PG, raise。"""
        mock_keyword_store.upsert.side_effect = RuntimeError("ES down")
        mock_pg_store._upsert_in_transaction.side_effect = RuntimeError("PG down")

        uc = _make_dual_write_use_case(
            mock_kb_repo,
            mock_embedder,
            mock_parser,
            mock_pg_store,
            mock_keyword_store,
        )

        with pytest.raises(RuntimeError):
            await uc.execute(
                kb_id="kb_test123",
                file_content=test_file_bytes,
                filename="test.md",
                content_type="text/markdown",
            )

        conn = mock_pg_store.acquire_connection.return_value
        # rollback
        conn.execute.assert_awaited_with("ROLLBACK")
        # release
        mock_pg_store.pool.release.assert_awaited_once_with(conn)
        # 不应 commit
        commit_calls = [
            c for c in conn.execute.call_args_list if c.args and c.args[0] == "COMMIT"
        ]
        assert len(commit_calls) == 0

    @pytest.mark.asyncio
    async def test_pg_ok_es_fail(
        self,
        mock_kb_repo,
        mock_embedder,
        mock_parser,
        mock_pg_store,
        mock_keyword_store,
        test_file_bytes,
    ):
        """PG 成功 ES 失败 → rollback PG + raise ES error。"""
        mock_keyword_store.upsert.side_effect = RuntimeError("ES down")
        # PG 正常（无 side_effect）

        uc = _make_dual_write_use_case(
            mock_kb_repo,
            mock_embedder,
            mock_parser,
            mock_pg_store,
            mock_keyword_store,
        )

        with pytest.raises(RuntimeError, match="ES down"):
            await uc.execute(
                kb_id="kb_test123",
                file_content=test_file_bytes,
                filename="test.md",
                content_type="text/markdown",
            )

        conn = mock_pg_store.acquire_connection.return_value
        # rollback
        conn.execute.assert_awaited_with("ROLLBACK")
        # release
        mock_pg_store.pool.release.assert_awaited_once_with(conn)
        # 不应 commit
        commit_calls = [
            c for c in conn.execute.call_args_list if c.args and c.args[0] == "COMMIT"
        ]
        assert len(commit_calls) == 0
        # upsert 不应被调用（快捷路径）
        mock_pg_store.upsert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pg_fail_es_ok(
        self,
        mock_kb_repo,
        mock_embedder,
        mock_parser,
        mock_pg_store,
        mock_keyword_store,
        test_file_bytes,
    ):
        """PG 失败 ES 成功 → delete ES orphan + raise PG error。"""
        pg_error = RuntimeError("PG constraint violation")
        mock_pg_store._upsert_in_transaction.side_effect = pg_error
        # ES 正常

        uc = _make_dual_write_use_case(
            mock_kb_repo,
            mock_embedder,
            mock_parser,
            mock_pg_store,
            mock_keyword_store,
        )

        with pytest.raises(RuntimeError, match="PG constraint violation"):
            await uc.execute(
                kb_id="kb_test123",
                file_content=test_file_bytes,
                filename="test.md",
                content_type="text/markdown",
            )

        conn = mock_pg_store.acquire_connection.return_value

        # ES delete 被调用以清理孤儿数据
        mock_keyword_store.delete.assert_awaited_once()
        del_kwargs = mock_keyword_store.delete.call_args
        assert del_kwargs[0][0] == "kb_test123"  # kb_id
        # chunk ids 应为 doc_id:{0,1,...}
        chunk_ids = del_kwargs[0][1]
        assert len(chunk_ids) > 0
        for cid in chunk_ids:
            assert cid.startswith("doc_")
            assert ":" in cid

        # rollback（_upsert_in_transaction 内部已有 BEGIN，需回滚）
        # 注意：PG 异常发生在 _upsert_in_transaction 内部，
        # 该方法在失败时不会自动 rollback（事务控制在外层），
        # 所以外层需要 rollback
        conn.execute.assert_any_call("ROLLBACK")

        # release
        mock_pg_store.pool.release.assert_awaited_once_with(conn)
        # 不应 commit
        commit_calls = [
            c for c in conn.execute.call_args_list if c.args and c.args[0] == "COMMIT"
        ]
        assert len(commit_calls) == 0
        # 快捷 upsert 不应被调用
        mock_pg_store.upsert.assert_not_awaited()


# ---------------------------------------------------------------------------
# 向后兼容测试 (es_enabled=False)
# ---------------------------------------------------------------------------


class TestUploadBackwardCompat:
    """es_enabled=False（默认）时行为应与改造前一致。"""

    @pytest.mark.asyncio
    async def test_es_disabled_uses_simple_upsert(
        self,
        mock_kb_repo,
        mock_embedder,
        mock_parser,
        mock_pg_store,
        test_file_bytes,
        expected_doc_id,
    ):
        """es_enabled=False → 走 store.upsert 便捷方法，不调 ES。"""
        from ragnexus.domain.chunking import heading_aware_split

        uc = UploadDocumentUseCase(
            kb_repo=mock_kb_repo,
            parser=mock_parser,
            embedder=mock_embedder,
            chunker=heading_aware_split,
            store=mock_pg_store,
            # 不传 keyword_store, es_enabled 默认 False
        )

        result = await uc.execute(
            kb_id="kb_test123",
            file_content=test_file_bytes,
            filename="test.md",
            content_type="text/markdown",
        )

        assert isinstance(result, UploadResult)
        mock_pg_store.upsert.assert_awaited_once_with("kb_test123", result.chunks)
        # 事务方法不应被调用
        mock_pg_store.acquire_connection.assert_not_awaited()
        mock_pg_store._upsert_in_transaction.assert_not_awaited()
