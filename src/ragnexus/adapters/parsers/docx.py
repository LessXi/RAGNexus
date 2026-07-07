"""DocxParser — 使用 mammoth convert_to_markdown 解析 Word 文档为 Sections。"""

import io

import mammoth

from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser
from ragnexus.domain.models import ParsedDocument, Section


class DocxParser:
    """Word .docx 解析器 — 实现 ParserPort。

    解析策略：mammoth.convert_to_markdown → MarkdownAndTextParser._parse_markdown。
    mammoth 是公开 API，MarkdownAndTextParser 已验证有效，无额外依赖风险。
    """

    async def parse(self, content: bytes, filename: str) -> ParsedDocument:
        result = mammoth.convert_to_markdown(io.BytesIO(content))
        md_text = result.value
        warnings = [w.message for w in result.messages]

        # 复用现有 Markdown 解析器按标题拆 sections
        md_parser = MarkdownAndTextParser()
        parsed = md_parser._parse_markdown(md_text, filename)
        sections = (
            parsed.sections
            if parsed.sections
            else [Section(heading=None, level=0, content=md_text)]
        )

        return ParsedDocument(
            filename=filename,
            sections=sections,
            raw_text=md_text,
            source_type="docx",
            metadata={"parser": "mammoth", "warnings": warnings},
        )
