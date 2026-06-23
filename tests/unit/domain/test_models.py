"""Tests for domain/models.py."""

from datetime import datetime

from domain.models import KnowledgeBase, Chunk, SearchHit


def test_knowledge_base_creation():
    kb = KnowledgeBase(id="kb_abc12345", name="产品手册", created_at=datetime.now())
    assert kb.id == "kb_abc12345"
    assert kb.name == "产品手册"
    assert isinstance(kb.created_at, datetime)


def test_chunk_id_format():
    """chunk.id = '{doc_id}:{index}'."""
    c = Chunk(
        id="doc_abc:3",
        kb_id="kb_xyz",
        doc_id="doc_abc",
        text="some text",
        vector=[0.1, 0.2],
        metadata={"chunk_index": 3},
    )
    assert c.id == "doc_abc:3"
    assert c.kb_id == "kb_xyz"
    assert c.doc_id == "doc_abc"


def test_searchhit_score_is_float():
    h = SearchHit(
        chunk_id="doc_abc:3",
        kb_id="kb_xyz",
        doc_id="doc_abc",
        score=0.823456,
        text="产品保修期三年",
        metadata={},
    )
    assert isinstance(h.score, float)
    assert 0.0 <= h.score <= 1.0
