"""MarkdownAndTextParser — 文档解析适配器。

实现 ParserPort。.md 按标题解析，.txt 退回原始文本。
"""

import re

from ragnexus.domain.models import ParsedDocument, Section


class MarkdownAndTextParser:
    """解析 Markdown（按标题分段）或纯文本（原始）。"""

    async def parse(self, content: bytes, filename: str) -> ParsedDocument:
        """按文件扩展名将字节内容解析为 ParsedDocument。"""
        text = content.decode("utf-8", errors="replace")
        if filename.lower().endswith(".md"):
            return self._parse_markdown(text, filename)
        return ParsedDocument(filename=filename, sections=[], raw_text=text)

    def _parse_markdown(self, text: str, filename: str) -> ParsedDocument:
        """按标题级别将 Markdown 文本拆分为章节。"""
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
