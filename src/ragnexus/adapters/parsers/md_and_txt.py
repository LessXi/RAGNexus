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
        """按标题级别将 Markdown 文本拆分为章节。

        追踪 fenced code block（``` 和 ~~~），防止代码块内的 ``#`` 被误识别为标题。
        """
        sections: list[Section] = []
        current_heading: str | None = None
        current_level: int = 0
        buffer: list[str] = []
        in_fence: bool = False
        fence_char: str = ""

        for line in text.splitlines():
            stripped = line.strip()

            # 检测 fenced code block 边界
            if stripped.startswith("```") or stripped.startswith("~~~"):
                if not in_fence:
                    in_fence = True
                    fence_char = stripped[0]
                elif stripped.startswith(fence_char * 3):
                    in_fence = False
                    fence_char = ""
                # 在 fence 内遇到不同 fencing 字符的 ```/~~~？不管，继续
                # 这种情况只会在不规范文档中出现

            # 在 fenced code block 内：跳过标题匹配，原样追加
            if in_fence:
                buffer.append(line)
                continue

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
