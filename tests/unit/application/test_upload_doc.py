"""Tests for UploadDocumentUseCase — full pipeline TDD."""

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from domain.errors import (
    DuplicateDocumentError,
    EmptyFileError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from domain.models import Chunk, ParsedDocument, Section, UploadResult

from application.upload_doc_use_case import UploadDocumentUseCase


@pytest.fixture
def mock_kb_repo():
    repo = MagicMock()
    repo.exists = AsyncMock(return_value=True)
    repo.doc_exists = AsyncMock(return_value=False)
    return repo


@pytest.fixture
def mock_parser():
    parser = MagicMock()
    parser.parse.return_value = ParsedDocument(
        filename="test.md",
        sections=[Section(heading="Intro", level=1, content="Hello world.")],
        raw_text="# Intro\n\nHello world.",
    )
    return parser


@pytest.fixture
def mock_embedder():
    emb = MagicMock()
    emb.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    return emb


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.upsert = AsyncMock()
    return store


@pytest.fixture
def use_case(mock_kb_repo, mock_embedder, mock_parser, mock_store):
    from domain.chunking import heading_aware_split
    return UploadDocumentUseCase(
        kb_repo=mock_kb_repo,
        parser=mock_parser,
        embedder=mock_embedder,
        chunker=heading_aware_split,
        store=mock_store,
    )


class TestUploadDocument:
    """Suite for UploadDocumentUseCase.execute()."""

    @pytest.mark.asyncio
    async def test_upload_success(
        self, use_case, mock_kb_repo, mock_parser, mock_embedder, mock_store
    ):
        """Valid markdown file returns UploadResult with correct doc_id, kb_id, chunks."""
        file_bytes = b"# Hello\n\nThis is a test document."
        result = await use_case.execute(
            kb_id="kb_test123",
            file_content=file_bytes,
            filename="test.md",
            content_type="text/markdown",
        )

        assert isinstance(result, UploadResult)
        assert result.kb_id == "kb_test123"
        assert result.doc_id.startswith("doc_")

        # doc_id = SHA256(file_content)[:16] with doc_ prefix
        expected_hash = "doc_" + hashlib.sha256(file_bytes).hexdigest()[:16]
        assert result.doc_id == expected_hash

        # All chunks carry correct kb_id and doc_id
        for chunk in result.chunks:
            assert chunk.kb_id == "kb_test123"
            assert chunk.doc_id == expected_hash

        # Metadata fields present per spec
        first = result.chunks[0]
        assert first.metadata["chunk_index"] == 0
        assert first.metadata["filename"] == "test.md"
        assert first.metadata["file_hash"] == hashlib.sha256(file_bytes).hexdigest()
        assert first.metadata["file_size"] == len(file_bytes)
        assert first.metadata["content_type"] == "text/markdown"

        # Heading metadata from Section info
        assert first.metadata["heading"] == "Intro"
        assert first.metadata["heading_level"] == 1

        # Transactional write called
        mock_store.upsert.assert_awaited_once_with("kb_test123", result.chunks)

    @pytest.mark.asyncio
    async def test_file_too_large(self, use_case):
        """File exceeding MAX_FILE_SIZE raises PayloadTooLargeError."""
        file_bytes = b"x" * (10 * 1024 * 1024 + 1)
        with pytest.raises(PayloadTooLargeError) as exc:
            await use_case.execute(
                kb_id="kb_test123",
                file_content=file_bytes,
                filename="test.md",
                content_type="text/markdown",
            )
        assert exc.value.code == 1301

    @pytest.mark.asyncio
    async def test_wrong_extension(self, use_case):
        """File with unsupported extension raises UnsupportedMediaTypeError."""
        for bad_name in ("test.pdf", "test.docx", "image.png", "notes"):
            with pytest.raises(UnsupportedMediaTypeError) as exc:
                await use_case.execute(
                    kb_id="kb_test123",
                    file_content=b"some content",
                    filename=bad_name,
                    content_type="application/octet-stream",
                )
            assert exc.value.code == 1300

    @pytest.mark.asyncio
    async def test_kb_not_found(self, mock_kb_repo, mock_embedder, mock_parser, mock_store):
        """Non-existent kb_id raises NotFoundError."""
        from domain.chunking import heading_aware_split
        mock_kb_repo.exists.return_value = False
        uc = UploadDocumentUseCase(
            kb_repo=mock_kb_repo,
            parser=mock_parser,
            embedder=mock_embedder,
            chunker=heading_aware_split,
            store=mock_store,
        )
        with pytest.raises(NotFoundError) as exc:
            await uc.execute(
                kb_id="kb_nonexistent",
                file_content=b"content",
                filename="test.md",
                content_type="text/markdown",
            )
        assert exc.value.code == 1100

    @pytest.mark.asyncio
    async def test_duplicate_doc(
        self, mock_kb_repo, mock_embedder, mock_parser, mock_store
    ):
        """Duplicate doc_id (SHA256 collision) raises DuplicateDocumentError BEFORE parsing."""
        from domain.chunking import heading_aware_split
        mock_kb_repo.doc_exists.return_value = True
        uc = UploadDocumentUseCase(
            kb_repo=mock_kb_repo,
            parser=mock_parser,
            embedder=mock_embedder,
            chunker=heading_aware_split,
            store=mock_store,
        )
        with pytest.raises(DuplicateDocumentError) as exc:
            await uc.execute(
                kb_id="kb_test123",
                file_content=b"some content",
                filename="test.md",
                content_type="text/markdown",
            )
        assert exc.value.code == 1201

        # Parser should NOT have been called (dedup check before parsing)
        mock_parser.parse.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_file(self, mock_kb_repo, mock_embedder, mock_parser, mock_store):
        """File with no content (parser returns empty) raises EmptyFileError."""
        from domain.chunking import heading_aware_split
        mock_parser.parse.return_value = ParsedDocument(
            filename="test.md",
            sections=[],
            raw_text="",
        )
        uc = UploadDocumentUseCase(
            kb_repo=mock_kb_repo,
            parser=mock_parser,
            embedder=mock_embedder,
            chunker=heading_aware_split,
            store=mock_store,
        )
        with pytest.raises(EmptyFileError) as exc:
            await uc.execute(
                kb_id="kb_test123",
                file_content=b"",
                filename="test.md",
                content_type="text/markdown",
            )
        assert exc.value.code == 1400
