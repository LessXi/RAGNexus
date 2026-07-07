"""PdfParser 单元测试 — mock fitz。"""

from unittest.mock import MagicMock, patch

import pytest

from ragnexus.adapters.parsers.pdf import PdfParser
from ragnexus.core.errors import AppError, ErrorCode


@pytest.fixture
def parser():
    return PdfParser()


class TestPdfParser:
    """PdfParser.parse 测试。"""

    @pytest.mark.asyncio
    @patch("ragnexus.adapters.parsers.pdf.fitz")
    async def test_parse_text_pdf(self, mock_fitz, parser):
        """有文字 PDF 按页创建 Section。"""
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page 1 content"
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_fitz.open.return_value = mock_doc

        result = await parser.parse(b"fake pdf", "doc.pdf")

        assert result.source_type == "pdf"
        assert result.metadata["parser"] == "pymupdf"
        assert len(result.sections) == 1
        assert result.sections[0].heading == "第 1 页"

    @pytest.mark.asyncio
    @patch("ragnexus.adapters.parsers.pdf.fitz")
    async def test_parse_scanned_pdf_raises(self, mock_fitz, parser):
        """扫描件（无文字）抛 DOCUMENT_PARSE_FAILED。"""
        mock_page = MagicMock()
        mock_page.get_text.return_value = ""  # 空页
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_fitz.open.return_value = mock_doc

        with pytest.raises(AppError) as exc_info:
            await parser.parse(b"scanned pdf", "scan.pdf")

        assert exc_info.value.code == ErrorCode.DOCUMENT_PARSE_FAILED.code
