"""文档解析适配器 — ParserPort 实现和 registry。"""

from ragnexus.adapters.parsers.docx import DocxParser
from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser
from ragnexus.adapters.parsers.pdf import PdfParser
from ragnexus.adapters.parsers.registry import get_parser, register

__all__ = [
    "MarkdownAndTextParser",
    "DocxParser",
    "PdfParser",
    "register",
    "get_parser",
]
