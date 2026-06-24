"""Text chunking strategies — heading-aware for .md, fixed-size for .txt."""

from ragnexus.domain.models import ParsedDocument


def heading_aware_split(
    parsed: ParsedDocument, max_chars: int = 1500, overlap: int = 50
) -> list[dict]:
    """Split by # headings; fall back to fixed-size if a section exceeds max_chars.

    Returns a list of dicts, each with ``text``, ``heading``, and ``heading_level``.
    Filter out empty chunks.
    """
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
            pieces.append({"text": text, "heading": s.heading, "heading_level": s.level})
        else:
            for sub in fixed_size_split(text, max_chars, overlap):
                if sub.strip():
                    pieces.append({"text": sub, "heading": s.heading, "heading_level": s.level})
    return pieces


def fixed_size_split(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split text by fixed character window with overlap."""
    if not text:
        return []
    step = max_chars - overlap
    return [text[i : i + max_chars] for i in range(0, max(len(text), 1), step)]
