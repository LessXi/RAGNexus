"""Tests for MarkdownAndTextParser — TDD RED phase."""

import pytest

from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser
from ragnexus.domain.models import ParsedDocument


@pytest.fixture
def parser():
    """Return a MarkdownAndTextParser."""
    return MarkdownAndTextParser()


class TestParseMarkdown:
    """Tests for parsing .md files."""

    async def test_parse_md_with_headings(self, parser):
        """Markdown with headings should create Sections with heading/level/content."""
        content = b"# Title\n\nSome content\n\n## Subtitle\n\nMore content here"
        result = await parser.parse(content, "test.md")

        assert isinstance(result, ParsedDocument)
        assert len(result.sections) == 2

        s1 = result.sections[0]
        assert s1.heading == "Title"
        assert s1.level == 1
        assert s1.content == "Some content"

        s2 = result.sections[1]
        assert s2.heading == "Subtitle"
        assert s2.level == 2
        assert s2.content == "More content here"

    async def test_parse_md_no_headings(self, parser):
        """Markdown without headings should create one Section with heading=None."""
        content = b"Just a line\n\nAnother line\n\nAnd one more"
        result = await parser.parse(content, "test.md")

        assert isinstance(result, ParsedDocument)
        assert len(result.sections) == 1
        section = result.sections[0]
        assert section.heading is None
        assert section.level == 0
        assert "Just a line" in section.content
        assert "Another line" in section.content

    async def test_parse_md_empty_heading(self, parser):
        """Markdown starting directly with content (no heading) should still create one section."""
        content = b"Just text without any heading at all\n\nSecond paragraph"
        result = await parser.parse(content, "test.md")

        assert isinstance(result, ParsedDocument)
        assert len(result.sections) >= 1
        assert result.raw_text is not None


class TestParseTxt:
    """Tests for parsing .txt files."""

    async def test_parse_txt(self, parser):
        """Plain text should return raw_text with empty sections list."""
        content = b"Plain text content\nNo parsing needed"
        result = await parser.parse(content, "test.txt")

        assert isinstance(result, ParsedDocument)
        assert result.filename == "test.txt"
        assert result.sections == []
        assert result.raw_text == "Plain text content\nNo parsing needed"

    async def test_parse_txt_utf8(self, parser):
        """Plain text with UTF-8 content should decode correctly."""
        content = "中文内容\n第二行".encode()
        result = await parser.parse(content, "notes.txt")

        assert result.sections == []
        assert "中文内容" in result.raw_text
