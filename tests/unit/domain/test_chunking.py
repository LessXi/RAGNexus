"""Tests for domain/chunking.py."""

from domain.chunking import fixed_size_split, heading_aware_split
from domain.models import ParsedDocument, Section


def make_parsed(sections: list[Section], raw_text: str = "") -> ParsedDocument:
    return ParsedDocument(filename="test.md", sections=sections, raw_text=raw_text)


def test_heading_aware_split_with_headings():
    """Markdown with # headings should split by heading."""
    parsed = make_parsed(
        sections=[
            Section(heading="Intro", level=1, content="Welcome to the docs."),
            Section(heading="API", level=1, content="POST /upload - upload files."),
        ],
        raw_text="# Intro\n\nWelcome to the docs.\n\n# API\n\nPOST /upload - upload files.",
    )
    chunks = heading_aware_split(parsed, max_chars=500, overlap=50)
    assert len(chunks) == 2
    assert "# Intro" in chunks[0]
    assert "# API" in chunks[1]


def test_fixed_size_split():
    """Plain text should be split by fixed character window."""
    text = "A" * 2500
    chunks = fixed_size_split(text, max_chars=1000, overlap=100)
    # 2500 chars with step=900 -> ceil(2500/900) = 3 chunks
    assert len(chunks) == 3
    assert all(len(c) > 0 for c in chunks)


def test_empty_input():
    """Empty text returns empty list."""
    assert fixed_size_split("", 1000, 50) == []
    parsed = make_parsed(sections=[], raw_text="")
    assert heading_aware_split(parsed) == []


def test_overlap():
    """Overlap should cause adjacent chunks to share content."""
    text = "0123456789" * 100  # 1000 chars
    chunks = fixed_size_split(text, max_chars=300, overlap=50)
    # chunk 0: text[0:300], chunk 1: text[250:550]
    assert chunks[0][-50:] == text[250:300]
