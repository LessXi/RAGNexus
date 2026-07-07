"""PdfParser — 使用 PyMuPDF 按页抽取文字。"""

import fitz  # PyMuPDF

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import ParsedDocument, Section


class PdfParser:
    """PDF 解析器 — 实现 ParserPort。

    策略：按页抽取文字，每页作为独立 Section（heading="第 N 页", level=2）。
    若所有页均无文字，判定为扫描件并抛 DOCUMENT_PARSE_FAILED。
    """

    async def parse(self, content: bytes, filename: str) -> ParsedDocument:
        doc = fitz.open(stream=content, filetype="pdf")
        sections: list[Section] = []
        raw_parts: list[str] = []

        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            if text:
                sections.append(
                    Section(
                        heading=f"第 {i + 1} 页",
                        level=2,
                        content=text,
                    )
                )
                raw_parts.append(text)

        page_count = len(doc)
        doc.close()

        if not sections:
            raise AppError(
                ErrorCode.DOCUMENT_PARSE_FAILED,
                "疑似扫描件，本期不支持 OCR",
            )

        return ParsedDocument(
            filename=filename,
            sections=sections,
            raw_text="\n\n".join(raw_parts),
            source_type="pdf",
            metadata={"parser": "pymupdf", "page_count": page_count},
        )
