"""领域模型 — 纯 dataclass，无框架依赖。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class KnowledgeBase:
    id: str  # "kb_" + nanoid(8)
    name: str  # user input
    created_at: datetime


@dataclass
class Section:
    heading: str | None  # None means no heading
    level: int  # 1-6, 0 means no heading
    content: str


@dataclass
class ParsedDocument:
    filename: str
    sections: list[Section]
    raw_text: str  # full text for fallback splitting


@dataclass
class Chunk:
    id: str  # "{doc_id}:{index}"
    kb_id: str
    doc_id: str
    text: str
    vector: list[float]  # length == EMBED_DIM
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchHit:
    chunk_id: str
    kb_id: str
    doc_id: str
    score: float  # higher = more relevant (1 - cosine distance)
    text: str
    metadata: dict[str, Any]


@dataclass
class UploadResult:
    doc_id: str
    kb_id: str
    chunks: list[Chunk]  # used internally by use case; router should use chunk_count
    chunk_count: int = 0
