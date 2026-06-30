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


class TestParseMarkdownCodeFence:
    """验证 fenced code block 内的 # 不被误识别为标题。"""

    async def test_code_block_preserved(self, parser):
        """代码块中的 Python 注释 ``#`` 不应创建幽灵 section。"""
        content = "## 安装指南\n\n```python\n# 这是注释，不是标题\nprint('hello')\n```\n\n## 配置\n\n设置数据库连接。".encode()
        result = await parser.parse(content, "test.md")

        assert len(result.sections) == 2
        assert result.sections[0].heading == "安装指南"
        assert "print" in result.sections[0].content
        assert result.sections[1].heading == "配置"
        assert "数据库连接" in result.sections[1].content

    async def test_tilde_fence_preserved(self, parser):
        """Tilde fence 也应正确追踪，不会泄漏。"""
        content = (
            "## 说明\n\n~~~sh\n# shell 注释\necho done\n~~~\n\n后面文字。".encode()
        )
        result = await parser.parse(content, "test.md")

        assert len(result.sections) == 1
        assert result.sections[0].heading == "说明"
        assert "shell 注释" in result.sections[0].content
        assert "echo done" in result.sections[0].content
        assert "后面文字" in result.sections[0].content

    async def test_mixed_headings_and_code(self, parser):
        """真实场景：多个标题 + 多个代码块交错。"""
        content = (
            "# 总览\n\n项目介绍。\n\n"
            "## API\n\n```python\ndef foo():\n    # 内部注释\n    pass\n```\n\n"
            "### 参数\n\n|字段|类型|\n|---|---|\n|name|str|\n\n"
            '```json\n# JSON 没有注释，但这行有 #\n{"key": "value"}\n```\n\n'
            "## FAQ\n\n常见问题。"
        ).encode()
        result = await parser.parse(content, "test.md")

        headings = [s.heading for s in result.sections]
        assert headings == ["总览", "API", "参数", "FAQ"]
        # API section 应包含 Python 代码块内容
        assert "def foo" in result.sections[1].content
        assert "# 内部注释" in result.sections[1].content
        # 参数 section 应包含 JSON 代码块
        assert "key" in result.sections[2].content

    async def test_headings_inside_code_block_are_not_sections(self, parser):
        """代码块中的 ``## Title`` 行不应被识别为标题。"""
        content = "## 步骤\n\n```\n## 这看起来像标题但实际在代码块中\n正文内容\n```\n\n继续正文。".encode()
        result = await parser.parse(content, "test.md")

        assert len(result.sections) == 1
        assert result.sections[0].heading == "步骤"
        assert "这看起来像标题但实际在代码块中" in result.sections[0].content


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
