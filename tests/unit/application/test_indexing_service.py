"""IndexingService 单元测试 — execute 幂等、成功路径、失败路径、purge_document_chunks。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ragnexus.application.indexing_service import IndexingService, purge_document_chunks
from ragnexus.domain.models import DocStatus, Document, ParsedDocument, Section


def _make_doc(
    doc_id: str = "doc_abc",
    status: DocStatus = DocStatus.PROCESSING,
    content: str = "# Title\n\nContent.",
) -> Document:
    """工厂：构造测试用 Document。"""
    return Document(
        doc_id=doc_id,
        kb_id="kb_test",
        filename="test.md",
        file_hash="abc123",
        file_size=100,
        content_type="text/markdown",
        content=content,
        status=status,
    )


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def mock_doc_repo():
    repo = MagicMock()
    repo.get = AsyncMock()
    repo.update_status = AsyncMock()
    return repo


@pytest.fixture
def mock_parser():
    parser = MagicMock()
    parser.parse = AsyncMock()
    return parser


@pytest.fixture
def mock_embedder():
    emb = MagicMock()
    emb.embed = AsyncMock()
    return emb


@pytest.fixture
def mock_chunker():
    return MagicMock()


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.upsert = AsyncMock()
    return store


@pytest.fixture
def mock_keyword_store():
    ks = MagicMock()
    ks.upsert = AsyncMock()
    ks.delete = AsyncMock()
    return ks


@pytest.fixture
def svc(mock_doc_repo, mock_parser, mock_embedder, mock_chunker, mock_store):
    """构造 IndexingService，默认 es_enabled=False。"""
    return IndexingService(
        doc_repo=mock_doc_repo,
        parser=mock_parser,
        embedder=mock_embedder,
        chunker=mock_chunker,
        store=mock_store,
        es_enabled=False,
    )


@pytest.fixture
def svc_es(
    mock_doc_repo,
    mock_parser,
    mock_embedder,
    mock_chunker,
    mock_store,
    mock_keyword_store,
):
    """构造 IndexingService，es_enabled=True + keyword_store。"""
    return IndexingService(
        doc_repo=mock_doc_repo,
        parser=mock_parser,
        embedder=mock_embedder,
        chunker=mock_chunker,
        store=mock_store,
        keyword_store=mock_keyword_store,
        es_enabled=True,
    )


# ── execute 幂等测试 ──────────────────────────────────────────────────


class TestExecuteIdempotence:
    """幂等保护：不存在跳过，非 PROCESSING 跳过。"""

    @pytest.mark.asyncio
    async def test_nonexistent_doc_returns_early(self, svc, mock_doc_repo):
        """文档不存在时仅记录日志并返回，不调用任何下游。"""
        mock_doc_repo.get.return_value = None

        await svc.execute("doc_gone")

        mock_doc_repo.get.assert_awaited_once_with("doc_gone")
        mock_doc_repo.update_status.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_success_skips(self, svc, mock_doc_repo):
        """SUCCESS 状态文档跳过，不执行索引流水线。"""
        mock_doc_repo.get.return_value = _make_doc(status=DocStatus.SUCCESS)

        await svc.execute("doc_abc")

        mock_doc_repo.get.assert_awaited_once()
        mock_doc_repo.update_status.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_failed_skips(self, svc, mock_doc_repo):
        """FAILED 状态文档跳过（reindex 走独立 use case，不会直接调 execute）。"""
        mock_doc_repo.get.return_value = _make_doc(status=DocStatus.FAILED)

        await svc.execute("doc_abc")

        mock_doc_repo.update_status.assert_not_awaited()


# ── execute 失败路径 ──────────────────────────────────────────────────


class TestExecuteFailures:
    """失败路径覆盖：空内容、空分块、embedder 异常、store 异常。"""

    @pytest.mark.asyncio
    async def test_empty_content_fails(self, svc, mock_doc_repo, mock_parser):
        """解析后 sections 和 raw_text 均为空 → FAILED。"""
        mock_doc_repo.get.return_value = _make_doc()
        mock_parser.parse.return_value = ParsedDocument(
            filename="test.md", sections=[], raw_text=""
        )

        await svc.execute("doc_abc")

        mock_doc_repo.update_status.assert_awaited_once_with(
            "doc_abc", status=DocStatus.FAILED, error_message="文件内容为空"
        )

    @pytest.mark.asyncio
    async def test_empty_chunks_fails(
        self, svc, mock_doc_repo, mock_parser, mock_chunker
    ):
        """分块返回空列表 → FAILED。"""
        mock_doc_repo.get.return_value = _make_doc()
        mock_parser.parse.return_value = ParsedDocument(
            filename="test.md",
            sections=[Section(heading="H1", level=1, content="text")],
            raw_text="text",
        )
        mock_chunker.return_value = []

        await svc.execute("doc_abc")

        mock_doc_repo.update_status.assert_awaited_once_with(
            "doc_abc", status=DocStatus.FAILED, error_message="分块结果为空"
        )

    @pytest.mark.asyncio
    async def test_embedder_exception_fails(
        self, svc, mock_doc_repo, mock_parser, mock_chunker, mock_embedder
    ):
        """embedder 异常 → FAILED 并 re-raise。"""
        mock_doc_repo.get.return_value = _make_doc()
        mock_parser.parse.return_value = ParsedDocument(
            filename="test.md",
            sections=[Section(heading="H1", level=1, content="text")],
            raw_text="text",
        )
        mock_chunker.return_value = [{"text": "chunk1"}]
        mock_embedder.embed.side_effect = RuntimeError("embedder down")

        with pytest.raises(RuntimeError, match="embedder down"):
            await svc.execute("doc_abc")

        mock_doc_repo.update_status.assert_awaited_once()
        call_args = mock_doc_repo.update_status.call_args
        assert call_args.kwargs["status"] == DocStatus.FAILED
        assert "embedder down" in call_args.kwargs["error_message"]

    @pytest.mark.asyncio
    async def test_store_upsert_exception_fails(
        self, svc, mock_doc_repo, mock_parser, mock_chunker, mock_embedder, mock_store
    ):
        """store.upsert 异常 → FAILED 并 re-raise。"""
        mock_doc_repo.get.return_value = _make_doc()
        mock_parser.parse.return_value = ParsedDocument(
            filename="test.md",
            sections=[Section(heading="H1", level=1, content="text")],
            raw_text="text",
        )
        mock_chunker.return_value = [{"text": "chunk1"}]
        mock_embedder.embed.return_value = [[0.1, 0.2]]
        mock_store.upsert.side_effect = RuntimeError("store down")

        with pytest.raises(RuntimeError, match="store down"):
            await svc.execute("doc_abc")

        mock_doc_repo.update_status.assert_awaited_once()
        call_args = mock_doc_repo.update_status.call_args
        assert call_args.kwargs["status"] == DocStatus.FAILED


# ── execute 成功路径 ──────────────────────────────────────────────────


class TestExecuteSuccess:
    """成功路径：标准 upsert 和 ES 双写。"""

    @pytest.mark.asyncio
    async def test_success_standard_upsert(
        self, svc, mock_doc_repo, mock_parser, mock_chunker, mock_embedder, mock_store
    ):
        """es_enabled=False 时走 store.upsert 单写，成功后更新 SUCCESS。"""
        doc = _make_doc()
        mock_doc_repo.get.return_value = doc
        mock_parser.parse.return_value = ParsedDocument(
            filename="test.md",
            sections=[Section(heading="H1", level=1, content="text")],
            raw_text="text",
        )
        chunk_dicts = [{"text": "chunk1", "heading": "H1", "heading_level": 1}]
        mock_chunker.return_value = chunk_dicts
        vectors = [[0.1, 0.2]]
        mock_embedder.embed.return_value = vectors

        await svc.execute("doc_abc")

        # 1. parse called
        mock_parser.parse.assert_awaited_once_with(doc.content.encode(), doc.filename)
        # 2. chunker called
        mock_chunker.assert_called_once()
        # 3. embedder called
        mock_embedder.embed.assert_awaited_once_with(["chunk1"])
        # 4. store.upsert called with chunks
        mock_store.upsert.assert_awaited_once()
        upsert_call = mock_store.upsert.call_args
        # kb_id matches
        assert upsert_call.args[0] == "kb_test"
        # chunk_count correct
        chunks = upsert_call.args[1]
        assert len(chunks) == 1
        assert chunks[0].doc_id == "doc_abc"
        assert chunks[0].vector == vectors[0]
        # 5. status updated to SUCCESS
        mock_doc_repo.update_status.assert_awaited_once_with(
            "doc_abc", status=DocStatus.SUCCESS, chunk_count=1
        )

    @pytest.mark.asyncio
    async def test_success_dual_write_es_and_pg(
        self,
        svc_es,
        mock_doc_repo,
        mock_parser,
        mock_chunker,
        mock_embedder,
        mock_store,
        mock_keyword_store,
    ):
        """es_enabled=True → PG + ES 双写，成功后 COMMIT 并更新 SUCCESS。"""
        doc = _make_doc()
        mock_doc_repo.get.return_value = doc
        mock_parser.parse.return_value = ParsedDocument(
            filename="test.md",
            sections=[Section(heading="H1", level=1, content="text")],
            raw_text="text",
        )
        mock_chunker.return_value = [{"text": "chunk1"}]
        mock_embedder.embed.return_value = [[0.1, 0.2]]

        # Mock pg_store internals for dual-write path
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        mock_store.acquire_connection = AsyncMock(return_value=mock_conn)
        mock_store._upsert_in_transaction = AsyncMock()
        mock_store.pool = MagicMock()
        mock_store.pool.release = AsyncMock()

        await svc_es.execute("doc_abc")

        # Both stores called
        mock_keyword_store.upsert.assert_awaited_once()
        mock_store._upsert_in_transaction.assert_awaited_once()
        # COMMIT issued
        mock_conn.execute.assert_awaited_with("COMMIT")
        # conn released
        mock_store.pool.release.assert_awaited_once_with(mock_conn)
        # Status → SUCCESS
        mock_doc_repo.update_status.assert_awaited_once_with(
            "doc_abc", status=DocStatus.SUCCESS, chunk_count=1
        )

    @pytest.mark.asyncio
    async def test_dual_write_pg_fails_rollback_and_raise(
        self,
        svc_es,
        mock_doc_repo,
        mock_parser,
        mock_chunker,
        mock_embedder,
        mock_store,
        mock_keyword_store,
    ):
        """ES 成功但 PG 失败 → ROLLBACK + 清 ES 孤儿 + re-raise PG 异常。"""
        doc = _make_doc()
        mock_doc_repo.get.return_value = doc
        mock_parser.parse.return_value = ParsedDocument(
            filename="test.md",
            sections=[Section(heading="H1", level=1, content="text")],
            raw_text="text",
        )
        mock_chunker.return_value = [{"text": "chunk1"}]
        mock_embedder.embed.return_value = [[0.1, 0.2]]

        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        mock_store.acquire_connection = AsyncMock(return_value=mock_conn)
        pg_error = RuntimeError("PG write failed")
        mock_store._upsert_in_transaction = AsyncMock(side_effect=pg_error)
        mock_store.pool = MagicMock()
        mock_store.pool.release = AsyncMock()

        with pytest.raises(RuntimeError, match="PG write failed"):
            await svc_es.execute("doc_abc")

        # ROLLBACK
        mock_conn.execute.assert_awaited_with("ROLLBACK")
        # ES orphans cleaned up
        mock_keyword_store.delete.assert_awaited_once()
        # conn released
        mock_store.pool.release.assert_awaited_once_with(mock_conn)
        # Status → FAILED
        mock_doc_repo.update_status.assert_awaited_once()
        assert (
            mock_doc_repo.update_status.call_args.kwargs["status"] == DocStatus.FAILED
        )

    @pytest.mark.asyncio
    async def test_dual_write_es_fails_rollback_and_raise(
        self,
        svc_es,
        mock_doc_repo,
        mock_parser,
        mock_chunker,
        mock_embedder,
        mock_store,
        mock_keyword_store,
    ):
        """ES 失败但 PG 成功 → ROLLBACK + re-raise ES 异常。"""
        doc = _make_doc()
        mock_doc_repo.get.return_value = doc
        mock_parser.parse.return_value = ParsedDocument(
            filename="test.md",
            sections=[Section(heading="H1", level=1, content="text")],
            raw_text="text",
        )
        mock_chunker.return_value = [{"text": "chunk1"}]
        mock_embedder.embed.return_value = [[0.1, 0.2]]

        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        mock_store.acquire_connection = AsyncMock(return_value=mock_conn)
        mock_store._upsert_in_transaction = AsyncMock()
        es_error = RuntimeError("ES unavailable")
        mock_keyword_store.upsert = AsyncMock(side_effect=es_error)
        mock_store.pool = MagicMock()
        mock_store.pool.release = AsyncMock()

        with pytest.raises(RuntimeError, match="ES unavailable"):
            await svc_es.execute("doc_abc")

        # ROLLBACK (PG work discarded)
        mock_conn.execute.assert_awaited_with("ROLLBACK")
        # conn released
        mock_store.pool.release.assert_awaited_once_with(mock_conn)
        # Status → FAILED
        mock_doc_repo.update_status.assert_awaited_once()
        assert (
            mock_doc_repo.update_status.call_args.kwargs["status"] == DocStatus.FAILED
        )

    @pytest.mark.asyncio
    async def test_dual_write_both_fail(
        self,
        svc_es,
        mock_doc_repo,
        mock_parser,
        mock_chunker,
        mock_embedder,
        mock_store,
        mock_keyword_store,
    ):
        """ES 和 PG 同时失败 → ROLLBACK + re-raise PG 异常。"""
        doc = _make_doc()
        mock_doc_repo.get.return_value = doc
        mock_parser.parse.return_value = ParsedDocument(
            filename="test.md",
            sections=[Section(heading="H1", level=1, content="text")],
            raw_text="text",
        )
        mock_chunker.return_value = [{"text": "chunk1"}]
        mock_embedder.embed.return_value = [[0.1, 0.2]]

        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        mock_store.acquire_connection = AsyncMock(return_value=mock_conn)
        pg_error = RuntimeError("PG fail")
        mock_store._upsert_in_transaction = AsyncMock(side_effect=pg_error)
        mock_keyword_store.upsert = AsyncMock(side_effect=RuntimeError("ES fail"))
        mock_store.pool = MagicMock()
        mock_store.pool.release = AsyncMock()

        with pytest.raises(RuntimeError, match="PG fail"):
            await svc_es.execute("doc_abc")

        mock_conn.execute.assert_awaited_with("ROLLBACK")
        mock_doc_repo.update_status.assert_awaited_once()
        assert (
            mock_doc_repo.update_status.call_args.kwargs["status"] == DocStatus.FAILED
        )


# ── purge_document_chunks ─────────────────────────────────────────────


class TestPurgeDocumentChunks:
    """purge_document_chunks 模块级函数测试。"""

    @pytest.mark.asyncio
    async def test_with_keyword_store(self):
        """有 keyword_store 时调用 delete_by_document。"""
        store = MagicMock()
        ks = MagicMock()
        ks.delete_by_document = AsyncMock()

        await purge_document_chunks("doc_abc", store, ks)

        ks.delete_by_document.assert_awaited_once_with("doc_abc")

    @pytest.mark.asyncio
    async def test_without_keyword_store(self):
        """无 keyword_store 时不做任何操作（PG 依赖 ON DELETE CASCADE）。"""
        store = MagicMock()

        await purge_document_chunks("doc_abc", store, None)

        # 不应抛出异常即通过

    @pytest.mark.asyncio
    async def test_keyword_store_exception_swallowed(self):
        """keyword_store.delete_by_document 异常应被吞掉。"""
        store = MagicMock()
        ks = MagicMock()
        ks.delete_by_document = AsyncMock(side_effect=RuntimeError("ES down"))

        # 不应抛出异常
        await purge_document_chunks("doc_abc", store, ks)

        ks.delete_by_document.assert_awaited_once_with("doc_abc")
