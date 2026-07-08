"""Tests for domain/models.py."""

from datetime import datetime

from ragnexus.domain.models import Chunk, KnowledgeBase, SearchHit


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


def test_tenant_defaults():
    """Tenant 默认 status='active'，created_at 为 None。"""
    from ragnexus.domain.models import Tenant

    t = Tenant(id="t1", name="测试租户")
    assert t.id == "t1"
    assert t.name == "测试租户"
    assert t.status == "active"
    assert t.created_at is None


def test_tenant_disabled():
    """Tenant status='disabled' 显式设置。"""
    from ragnexus.domain.models import Tenant

    t = Tenant(id="t2", name="停用租户", status="disabled")
    assert t.status == "disabled"


def test_tenant_with_datetime():
    """Tenant 可注入 created_at。"""
    from datetime import datetime
    from ragnexus.domain.models import Tenant

    now = datetime.now()
    t = Tenant(id="t3", name="有时戳租户", created_at=now)
    assert t.created_at is now


def test_api_key_defaults():
    """ApiKey 默认 status='active', expires_at=None, created_at=None。"""
    from ragnexus.domain.models import ApiKey

    ak = ApiKey(
        id="550e8400-e29b-41d4-a716-446655440000",
        tenant_id="t1",
        key_hash="abc123hash",
        key_prefix="rk_a1b2",
        name="默认Key",
    )
    assert ak.status == "active"
    assert ak.expires_at is None
    assert ak.created_at is None


def test_api_key_revoked():
    """ApiKey status='revoked' 显式设置。"""
    from ragnexus.domain.models import ApiKey

    ak = ApiKey(
        id="uuid-2",
        tenant_id="t1",
        key_hash="def456hash",
        key_prefix="rk_c3d4",
        name="已吊销Key",
        status="revoked",
    )
    assert ak.status == "revoked"


def test_parsed_document_defaults():
    """ParsedDocument 默认 source_type='text', metadata={}"""
    from ragnexus.domain.models import ParsedDocument, Section

    doc = ParsedDocument(
        filename="test.txt",
        sections=[],
        raw_text="hello",
    )
    assert doc.source_type == "text"
    assert doc.metadata == {}


def test_document_new_fields_default_none():
    """Document 新字段 source_file_path/source_filename 默认为 None"""
    from ragnexus.domain.models import Document

    doc = Document(
        doc_id="d1",
        kb_id="k1",
        filename="f.txt",
        file_hash="h",
        file_size=10,
        content_type="text/plain",
        content="",
    )
    assert doc.source_file_path is None
    assert doc.source_filename is None
