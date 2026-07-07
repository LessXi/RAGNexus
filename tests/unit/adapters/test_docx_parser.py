"""DocxParser 单元测试 — mock mammoth 依赖。"""

from unittest.mock import MagicMock, patch, AsyncMock
import io

import pytest

from ragnexus.adapters.parsers.docx import DocxParser


@pytest.fixture
def parser():
    return DocxParser()


class TestDocxParser:
    """DocxParser.parse 测试 — mock mammoth.convert_to_markdown。"""

    @pytest.mark.asyncio
    @patch("ragnexus.adapters.parsers.docx.mammoth.convert_to_markdown")
    async def test_parse_with_headings(self, mock_convert, parser):
        """mammoth 输出 Markdown 标题 → sections 正确拆分。"""
        mock_convert.return_value = MagicMock(
            value="# 第一章\n\n这是内容。\n\n## 第一节\n\n小节内容。",
            messages=[],
        )

        result = await parser.parse(b"mock docx content", "test.docx")

        assert result.source_type == "docx"
        assert result.metadata["parser"] == "mammoth"
        assert len(result.sections) >= 2
        assert result.sections[0].heading == "第一章"
        assert result.sections[0].level == 1

    @pytest.mark.asyncio
    @patch("ragnexus.adapters.parsers.docx.mammoth.convert_to_markdown")
    async def test_parse_no_headings(self, mock_convert, parser):
        """mammoth 输出无标题纯文本 → 单个 section。"""
        mock_convert.return_value = MagicMock(
            value="这是纯文本内容，没有任何标题。",
            messages=[],
        )

        result = await parser.parse(b"mock content", "plain.docx")

        assert result.source_type == "docx"
        assert len(result.sections) >= 1

    @pytest.mark.asyncio
    @patch("ragnexus.adapters.parsers.docx.mammoth.convert_to_markdown")
    async def test_parse_captures_warnings(self, mock_convert, parser):
        """mammoth 返回 warnings → metadata 包含。"""
        mock_convert.return_value = MagicMock(
            value="# 标题\n内容",
            messages=[MagicMock(message="Unsupported element")],
        )

        result = await parser.parse(b"content", "warn.docx")
        assert "warnings" in result.metadata
        assert len(result.metadata["warnings"]) == 1
