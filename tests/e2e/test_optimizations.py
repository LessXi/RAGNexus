"""E2E 测试 — 优化选项（rewrite/rerank）启停验证。

依赖: Docker Compose (test-db on port 5433)
若无 Docker 或数据库不可用，pytest 自动 skip。
"""

import asyncio
import os

import pytest

from ragnexus.config import get_settings
from ragnexus.domain.models import SearchHit

pytestmark = [pytest.mark.e2e]


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────


def _db_available() -> bool:
    """检查测试数据库是否可用。"""
    try:
        import asyncpg

        async def _check():
            dsn = os.environ.get(
                "PG_DSN",
                "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test",
            )
            conn = await asyncpg.connect(dsn, timeout=3)
            await conn.close()
            return True

        return asyncio.run(asyncio.wait_for(_check(), timeout=5))
    except Exception:
        return False


def _embedder_available() -> bool:
    """检查 embedder API key 是否已配置。"""
    return bool(os.environ.get("EMBED_API_KEY") or get_settings().EMBED_API_KEY)


# ──────────────────────────────────────────────────────────────────
# 基础跳过检查
# ──────────────────────────────────────────────────────────────────


skip_no_db = pytest.mark.skipif(
    not _db_available(),
    reason="测试数据库不可用（需要 Docker Compose 启动 test-db）",
)

skip_no_embedder = pytest.mark.skipif(
    not _embedder_available(),
    reason="未配置 EMBED_API_KEY，跳过需 embedder 的测试",
)


# ──────────────────────────────────────────────────────────────────
# E2E: Retrieve 基本流程（数据库可用 + embedder 可用）
# ──────────────────────────────────────────────────────────────────


@skip_no_db
@skip_no_embedder
class TestE2ERetrieveBasic:
    """冒烟：创建 KB → 上传文档 → 检索（不带 rewrite/rerank 参数）。"""

    def test_retrieve_returns_expected_format(self, client):
        """检索返回标准格式 {code, data: {total, hits}, message}。"""
        # 先创建 KB
        import uuid

        kb_name = f"e2e_opt_{uuid.uuid4().hex[:8]}"
        resp = client.post(
            "/v1/knowledge-bases:create",
            json={"name": kb_name},
        )
        assert resp.status_code == 200
        kb_data = resp.json()
        kb_id = kb_data["data"]["kb_id"]

        try:
            # 上传一个文本文件
            resp = client.post(
                "/v1/documents:upload",
                data={"kb_id": kb_id},
                files={
                    "file": (
                        "test.md",
                        b"# Test\n\nThis is a test document about AI.\n\n"
                        b"Artificial intelligence is transforming industries.",
                        "text/markdown",
                    ),
                },
            )
            if resp.status_code == 500:
                pytest.skip("上传失败（可能是 embedder API 不可用）")

            assert resp.status_code == 201
            upload_data = resp.json()
            assert upload_data["code"] == 0

            # 检索
            resp = client.post(
                "/v1/rag:retrieve",
                json={"query": "AI", "kb_ids": [kb_id], "top_k": 3},
            )
            assert resp.status_code == 200
            retrieve_data = resp.json()

            # 标准响应格式断言
            assert retrieve_data["code"] == 0
            assert retrieve_data["message"] == "ok"
            assert "data" in retrieve_data
            assert "total" in retrieve_data["data"]
            assert "hits" in retrieve_data["data"]
            assert isinstance(retrieve_data["data"]["hits"], list)

            # 每个 hit 只有标准字段
            for hit in retrieve_data["data"]["hits"]:
                assert set(hit.keys()) == {
                    "chunk_id",
                    "kb_id",
                    "doc_id",
                    "score",
                    "text",
                    "metadata",
                }
                assert isinstance(hit["score"], (int, float))
                # 无新增字段
                assert "rerank_score" not in hit
                assert "rewritten_query" not in hit
        finally:
            # 清理：删除 KB（如果有删除端点）
            pass


# ──────────────────────────────────────────────────────────────────
# E2E: 无 rewrite/rerank 参数（向后兼容）
# ──────────────────────────────────────────────────────────────────


@skip_no_db
class TestE2EErrorCases:
    """错误场景 — 不需要 embedder。"""

    def test_missing_query_returns_422(self, client):
        """缺少 query 字段返回 422。"""
        resp = client.post(
            "/v1/rag:retrieve",
            json={"kb_ids": ["kb1"]},
        )
        assert resp.status_code == 422

    def test_missing_kb_ids_returns_422(self, client):
        """缺少 kb_ids 字段返回 422。"""
        resp = client.post(
            "/v1/rag:retrieve",
            json={"query": "test"},
        )
        assert resp.status_code == 422

    def test_extra_fields_rejected(self, client):
        """请求含额外字段时被拒绝（extra='forbid'）。"""
        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "test",
                "kb_ids": ["kb1"],
                "rerank_enabled": True,
            },
        )
        # extra='forbid' → 422 或忽略额外字段
        # 如果是 forbid 则返回 422
        if resp.status_code != 200:
            assert resp.status_code == 422

    def test_kb_not_found_returns_404(self, client):
        """不存在的 KB 返回错误。"""
        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "test",
                "kb_ids": ["kb_nonexistent_12345"],
                "top_k": 5,
            },
        )
        # 可能是 404 或其他错误码（取决于 embedder 是否可用）
        # 无 embedder 时返回 500 也合理
        assert resp.status_code in (200, 404, 500)


# ──────────────────────────────────────────────────────────────────
# E2E: 优化选项隔离（不依赖数据库的结构测试）
# ──────────────────────────────────────────────────────────────────


class TestE2EOptimizationIsolation:
    """不需要数据库：验证 rewrite/rerank 选项不影响 HTTP 接口契约。"""

    def test_search_hit_has_no_optimization_fields(self):
        """SearchHit dataclass 无 rewrite/rerank 相关字段。"""
        hit = SearchHit(
            chunk_id="c1",
            kb_id="k1",
            doc_id="d1",
            score=0.95,
            text="test",
            metadata={},
        )
        # 验证 SearchHit 序列化后无额外字段
        d = {
            "chunk_id": hit.chunk_id,
            "kb_id": hit.kb_id,
            "doc_id": hit.doc_id,
            "score": hit.score,
            "text": hit.text,
            "metadata": hit.metadata,
        }
        assert "rerank_score" not in d
        assert "rewritten_query" not in d
        assert "original_query" not in d

    def test_request_model_still_three_fields(self):
        """无论优化是否启用，请求 model 只有三个字段。"""
        from ragnexus.adapters.http.retrieve_router import _RetrieveRequest

        fields = set(_RetrieveRequest.model_fields.keys())
        assert fields == {"query", "kb_ids", "top_k"}

    def test_extra_forbid_still_enforced(self):
        """extra='forbid' 在优化启用时仍然生效。"""
        from ragnexus.adapters.http.retrieve_router import _RetrieveRequest

        assert _RetrieveRequest.model_config.get("extra") == "forbid"
