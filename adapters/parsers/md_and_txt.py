"""MarkdownAndTextParser — inbound adapter for document parsing.

Implements ParserPort. Heading-aware for .md, raw-text fallback for .txt.
"""

import re

from domain.models import ParsedDocument, Section


class MarkdownAndTextParser:
    """Parse markdown (heading-aware) or plain text (raw)."""

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        """Parse content bytes into a ParsedDocument based on file extension."""
        text = content.decode("utf-8", errors="replace")
        if filename.lower().endswith(".md"):
            return self._parse_markdown(text, filename)
        return ParsedDocument(filename=filename, sections=[], raw_text=text)

    def _parse_markdown(self, text: str, filename: str) -> ParsedDocument:
        """Split markdown text into sections by heading level."""
        sections: list[Section] = []
        current_heading: str | None = None
        current_level: int = 0
        buffer: list[str] = []

        for line in text.splitlines():
            m = re.match(r"^(#{1,6})\s+(.+)$", line)
            if m:
                # Flush current section before switching heading
                if buffer or current_heading is not None:
                    sections.append(
                        Section(
                            heading=current_heading,
                            level=current_level,
                            content="\n".join(buffer).strip(),
                        )
                    )
                current_level = len(m.group(1))
                current_heading = m.group(2).strip()
                buffer = []
            else:
                buffer.append(line)

        # Flush final section
        if buffer or current_heading is not None:
            sections.append(
                Section(
                    heading=current_heading,
                    level=current_level,
                    content="\n".join(buffer).strip(),
                )
            )

        # Remove completely empty sections (heading-only with no content)
        sections = [s for s in sections if s.content or s.heading]
        return ParsedDocument(filename=filename, sections=sections, raw_text=text)
