"""Text chunking strategies — heading-aware for .md, fixed-size for .txt."""

from domain.models import ParsedDocument


def heading_aware_split(
    parsed: ParsedDocument, max_chars: int = 1500, overlap: int = 50
) -> list[str]:
    """Split by # headings; fall back to fixed-size if a section exceeds max_chars.

    Filter out empty chunks.
    """
    if not any(s.heading for s in parsed.sections):
        return [c for c in fixed_size_split(parsed.raw_text, max_chars, overlap) if c.strip()]

    pieces: list[str] = []
    for s in parsed.sections:
        text = (f"# {s.heading}\n\n" if s.heading else "") + s.content
        if len(text) <= max_chars:
            pieces.append(text)
        else:
            pieces.extend(fixed_size_split(text, max_chars, overlap))
    return [p for p in pieces if p.strip()]


def fixed_size_split(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split text by fixed character window with overlap."""
    if not text:
        return []
    step = max_chars - overlap
    return [text[i : i + max_chars] for i in range(0, max(len(text), 1), step)]
