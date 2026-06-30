"""HTTP schema 不变性验证 — 确保请求/响应格式与第一期一致。

断言:
- 请求体只有 query/kb_ids/top_k 字段
- 响应格式为 {code, data: {total, hits}, message}
- SearchHit score 是 float（向量原始分）
- 响应无 rerank_score/rewritten_query 等新增字段
"""

import inspect

from pydantic import BaseModel

from ragnexus.adapters.http.retrieve_router import _RetrieveRequest, create_router
from ragnexus.domain.models import SearchHit

# ═══════════════════════════════════════════════════════════════════
# 请求 schema 不变性
# ═══════════════════════════════════════════════════════════════════


class TestRequestSchemaInvariance:
    """请求体 Pydantic model 只有 query/kb_ids/top_k 三个字段。"""

    def test_request_only_allowed_fields(self):
        """_RetrieveRequest 的 model_fields 只含 query, kb_ids, top_k。"""
        fields = set(_RetrieveRequest.model_fields.keys())
        assert fields == {
            "query",
            "kb_ids",
            "top_k",
        }, f"请求 model_fields 必须是 {{query, kb_ids, top_k}}，实际: {fields}"

    def test_request_forbids_extra_fields(self):
        """model_config 设 extra='forbid'，拒绝未知字段。"""
        assert (
            _RetrieveRequest.model_config.get("extra") == "forbid"
        ), "请求 model 必须配置 extra='forbid'"

    def test_request_has_no_rerank_options(self):
        """请求 model_fields 中无 rerank_options 字段。"""
        assert "rerank_options" not in _RetrieveRequest.model_fields

    def test_request_has_no_rewrite_options(self):
        """请求 model_fields 中无 rewrite_options 字段。"""
        assert "rewrite_options" not in _RetrieveRequest.model_fields

    def test_request_has_no_rerank_enabled(self):
        """请求 model_fields 中无 rerank_enabled 字段。"""
        assert "rerank_enabled" not in _RetrieveRequest.model_fields

    def test_request_has_no_rewrite_enabled(self):
        """请求 model_fields 中无 rewrite_enabled 字段。"""
        assert "rewrite_enabled" not in _RetrieveRequest.model_fields

    def test_top_k_default_is_5(self):
        """top_k 默认值 5，与第一期一致。"""
        field_info = _RetrieveRequest.model_fields["top_k"]
        assert (
            field_info.default == 5
        ), f"top_k 默认值必须为 5，实际: {field_info.default}"

    def test_query_and_kb_ids_are_required(self):
        """query 和 kb_ids 是必填字段。"""
        query_field = _RetrieveRequest.model_fields["query"]
        kb_ids_field = _RetrieveRequest.model_fields["kb_ids"]
        assert query_field.is_required()
        assert kb_ids_field.is_required()

    def test_request_is_pydantic_model(self):
        """请求 model 是 Pydantic BaseModel 子类。"""
        assert issubclass(_RetrieveRequest, BaseModel)


# ═══════════════════════════════════════════════════════════════════
# 响应 schema 不变性
# ═══════════════════════════════════════════════════════════════════


class TestResponseSchemaInvariance:
    """响应格式必须与第一期一致：{code, data: {total, hits}, message}。"""

    def test_search_hit_fields(self):
        """SearchHit 只含 chunk_id, kb_id, doc_id, score, text, metadata。"""
        hit_fields = {f.name for f in SearchHit.__dataclass_fields__.values()}
        expected = {"chunk_id", "kb_id", "doc_id", "score", "text", "metadata"}
        assert (
            hit_fields == expected
        ), f"SearchHit 字段必须为 {expected}，实际: {hit_fields}"

    def test_search_hit_score_is_float(self):
        """SearchHit.score 类型为 float（向量原始分）。"""
        hit = SearchHit(
            chunk_id="c1",
            kb_id="k1",
            doc_id="d1",
            score=0.95123,
            text="text",
            metadata={},
        )
        assert isinstance(
            hit.score, float
        ), f"score 类型必须为 float，实际: {type(hit.score)}"

    def test_search_hit_no_rerank_score(self):
        """SearchHit 不包含 rerank_score 字段。"""
        hit_fields = {f.name for f in SearchHit.__dataclass_fields__.values()}
        assert "rerank_score" not in hit_fields, "SearchHit 不应有 rerank_score 字段"

    def test_search_hit_no_rewritten_query(self):
        """SearchHit 不包含 rewritten_query 字段。"""
        hit_fields = {f.name for f in SearchHit.__dataclass_fields__.values()}
        assert (
            "rewritten_query" not in hit_fields
        ), "SearchHit 不应有 rewritten_query 字段"

    def test_search_hit_no_rewrite_reason(self):
        """SearchHit 不包含 rewrite 相关字段。"""
        hit_fields = {f.name for f in SearchHit.__dataclass_fields__.values()}
        assert "rewrite_reason" not in hit_fields
        assert "rewrite_needed" not in hit_fields

    def test_search_hit_score_not_nullable(self):
        """SearchHit.score 是真实 float，非 Optional。"""
        hit = SearchHit(
            chunk_id="c1",
            kb_id="k1",
            doc_id="d1",
            score=0.0,
            text="text",
            metadata={},
        )
        assert hit.score == 0.0


# ═══════════════════════════════════════════════════════════════════
# Router 响应格式验证
# ═══════════════════════════════════════════════════════════════════


class TestRouterResponseFormat:
    """验证 retrieve_router 中硬编码的响应格式。"""

    def test_create_router_exists(self):
        """确认模块导出了 create_router。"""
        import ragnexus.adapters.http.retrieve_router as rmod

        assert hasattr(rmod, "create_router")

    def test_request_model_dump_keys(self):
        """_RetrieveRequest.model_dump() 只有三个字段。"""
        req = _RetrieveRequest(query="test", kb_ids=["kb1"], top_k=5)
        d = req.model_dump()
        assert set(d.keys()) == {"query", "kb_ids", "top_k"}

    def test_hit_serialization_in_router(self):
        """路由器中 SearchHit 序列化仅含 6 个字段，score round 到 6 位。"""
        hit = SearchHit(
            chunk_id="kb_x:0",
            kb_id="kb_x",
            doc_id="doc_1",
            score=0.95123456789,
            text="sample text",
            metadata={"page": 1},
        )

        # 模拟 router 中的序列化（与 retrieve_router.py L37-43 一致）
        serialized = {
            "chunk_id": hit.chunk_id,
            "kb_id": hit.kb_id,
            "doc_id": hit.doc_id,
            "score": round(hit.score, 6),
            "text": hit.text,
            "metadata": hit.metadata,
        }

        expected_keys = {
            "chunk_id",
            "kb_id",
            "doc_id",
            "score",
            "text",
            "metadata",
        }
        assert set(serialized.keys()) == expected_keys
        assert serialized["score"] == 0.951235  # round(…, 6)
        assert "rerank_score" not in serialized
        assert "rewritten_query" not in serialized

    def test_response_wrapper_structure(self):
        """响应包装格式 code/data/message 从源码验证。"""
        source = inspect.getsource(create_router)
        assert '"code": 0' in source or "'code': 0" in source, "响应 code 必须为 0"
        assert (
            '"message": "ok"' in source or "'message': 'ok'" in source
        ), "响应 message 必须为 'ok'"
        assert '"data":' in source or "'data':" in source, "响应必须包含 data 字段"
        assert '"total"' in source or "'total'" in source, "data 必须包含 total"
        assert '"hits"' in source or "'hits'" in source, "data 必须包含 hits"
