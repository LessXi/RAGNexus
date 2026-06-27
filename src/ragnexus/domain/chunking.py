"""文本分块策略 — .md 按标题分割，.txt 固定窗口分割。"""

from ragnexus.domain.models import ParsedDocument


def heading_aware_split(
    parsed: ParsedDocument, max_chars: int = 1500, overlap: int = 50
) -> list[dict]:
    """按 # 标题分割；章节超过 max_chars 时回退到固定窗口分割。

    返回 dict 列表，每个含 ``text``、``heading``、``heading_level``。
    过滤空块。"""
    if not any(s.heading for s in parsed.sections):
        return [
            {"text": c, "heading": None, "heading_level": 0}
            for c in fixed_size_split(parsed.raw_text, max_chars, overlap)
            if c.strip()
        ]

    pieces: list[dict] = []
    for s in parsed.sections:
        text = (f"# {s.heading}\n\n" if s.heading else "") + s.content
        if len(text) <= max_chars:
            pieces.append(
                {"text": text, "heading": s.heading, "heading_level": s.level}
            )
        else:
            # 超大 section：单独对 content 做 fixed_size_split，再给每块独立拼 heading
            # 避免 heading 标记在 overlap 窗口处被切碎
            heading_prefix = f"# {s.heading}\n\n" if s.heading else ""
            content_chunks = fixed_size_split(
                s.content, max_chars - len(heading_prefix), overlap
            )
            for sub in content_chunks:
                if sub.strip():
                    pieces.append(
                        {
                            "text": heading_prefix + sub,
                            "heading": s.heading,
                            "heading_level": s.level,
                        }
                    )
    return pieces


def fixed_size_split(text: str, max_chars: int, overlap: int) -> list[str]:
    """按固定字符窗口 + 重叠分割文本。"""
    if not text:
        return []
    step = max_chars - overlap
    return [text[i : i + max_chars] for i in range(0, len(text), step)]
