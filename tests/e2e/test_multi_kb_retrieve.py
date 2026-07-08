"""E2E 多库联合检索测试 — 使用 FastAPI TestClient 模拟完整请求-响应链路。

测试场景覆盖:
- 单库向后兼容
- 双库跨域检索
- Free 套餐限制
- 跨租户 KB 拒绝
- 不存在的 KB
- 配额计数（多库仅计 1 次）
- 响应 meta 元信息
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ragnexus.adapters.http.error_handlers import register_error_handlers
from ragnexus.adapters.http.retrieve_router import (
    create_router as create_retrieve_router,
)
from ragnexus.core.auth import TenantContext
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import RetrieveResult, SearchHit
from ragnexus.observability import RetrieveObservability

# ── 覆盖 conftest 的 autouse DB 检查 ──────────────────────────────────
# 这些测试使用 mock 构建的 FastAPI app，无需真实数据库。


@pytest.fixture(autouse=True)
def _require_test_db():
    """覆盖 conftest.py 的 autouse fixture — 本测试文件使用 mock，无需 DB。"""
    pass


pytestmark = [
    pytest.mark.e2e,
]


# ── helpers ────────────────────────────────────────────────────────────


def _make_hit(
    chunk_id: str,
    kb_id: str = "kb_test",
    doc_id: str = "",
    score: float = 0.9,
    text: str = "test chunk",
    kb_name: str = "",
    metadata: dict | None = None,
) -> SearchHit:
    """构造测试用 SearchHit。"""
    return SearchHit(
        chunk_id=chunk_id,
        kb_id=kb_id,
        doc_id=doc_id or f"doc_{chunk_id}",
        score=score,
        text=text,
        metadata=metadata or {},
        kb_name=kb_name,
    )


def _make_result(
    hits: list[SearchHit] | None = None,
    total: int = 0,
    latency_ms: int = 42,
    mode: str = "hybrid",
    vector_count: int = 0,
    bm25_count: int = 0,
    fused_count: int = 0,
    degraded: bool = False,
    degraded_reason: str | None = None,
    degraded_kb_ids: list[str] | None = None,
) -> RetrieveResult:
    """构造测试用 RetrieveResult。"""
    return RetrieveResult(
        hits=hits or [],
        total=total,
        latency_ms=latency_ms,
        mode=mode,
        vector_count=vector_count,
        bm25_count=bm25_count,
        fused_count=fused_count,
        rerank_model=None,
        degraded=degraded,
        degraded_reason=degraded_reason,
        degraded_kb_ids=degraded_kb_ids or [],
    )


def _build_app(
    mock_retrieve_uc: AsyncMock,
    *,
    plan: str = "pro",
    rate_limiter: object = None,
    tenant_id: str = "default",
) -> FastAPI:
    """构建带 mocked retrieve use case 的 FastAPI 应用。

    参数:
        mock_retrieve_uc: mocked RetrieveUseCase
        plan: 租户套餐名 (free/standard/pro)
        rate_limiter: 可选 mocked rate limiter
        tenant_id: 租户 ID
    """

    async def mock_get_current_tenant() -> TenantContext:
        return TenantContext(
            tenant_id=tenant_id,
            tenant_name="测试租户",
            key_id="test_key",
            key_prefix="test",
            plan=plan,
        )

    app = FastAPI()
    app.include_router(
        create_retrieve_router(
            mock_retrieve_uc,
            mock_get_current_tenant,
            rate_limiter=rate_limiter,
        )
    )
    app.state.langfuse_client = RetrieveObservability(enabled=False)
    register_error_handlers(app)
    return app


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def mock_retrieve_uc() -> AsyncMock:
    """返回 mocked RetrieveUseCase。"""
    return AsyncMock()


@pytest.fixture
def client(mock_retrieve_uc: AsyncMock) -> TestClient:
    """默认 pro 套餐 TestClient — 支持最多 5 库联合检索。"""
    app = _build_app(mock_retrieve_uc, plan="pro")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def free_plan_client(mock_retrieve_uc: AsyncMock) -> TestClient:
    """Free 套餐 TestClient — max_kb_per_retrieve=1。"""
    app = _build_app(mock_retrieve_uc, plan="free")
    return TestClient(app, raise_server_exceptions=False)


# ── 测试用例 ────────────────────────────────────────────────────────────


class TestSingleKbBackwardCompat:
    """单库检索向后兼容性 — kb_ids 单元素行为与旧版一致。"""

    def test_single_kb_returns_200_with_expected_shape(
        self, client: TestClient, mock_retrieve_uc: AsyncMock
    ):
        """单库检索返回标准响应格式，hits 包含 kb_name。"""
        mock_retrieve_uc.execute.return_value = _make_result(
            hits=[
                _make_hit("ch1", kb_id="kb_a", kb_name="知识库A", score=0.95),
                _make_hit("ch2", kb_id="kb_a", kb_name="知识库A", score=0.82),
            ],
            total=2,
            vector_count=20,
            bm25_count=20,
            fused_count=2,
        )

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "kb_ids": ["kb_a"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["message"] == "ok"
        assert data["data"]["query"] == "测试查询"
        assert data["data"]["kb_ids"] == ["kb_a"]
        hits = data["data"]["hits"]
        assert len(hits) == 2
        assert hits[0]["kb_name"] == "知识库A"
        assert hits[1]["kb_name"] == "知识库A"
        # 单库 meta
        meta = data["data"]["meta"]
        assert meta["multi_kb"] is False
        assert meta["kb_count"] == 1
        assert meta["fusion"] == "rrf"
        assert meta["rrf_k"] == 60
        assert "per_kb_top_k" in meta

    def test_single_kb_no_hits(self, client: TestClient, mock_retrieve_uc: AsyncMock):
        """单库无结果返回空 hits，不报错。"""
        mock_retrieve_uc.execute.return_value = _make_result(
            hits=[],
            total=0,
        )

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "不存在的概念",
                "kb_ids": ["kb_a"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["hits"] == []
        assert data["data"]["meta"]["total"] == 0
        assert data["data"]["meta"]["multi_kb"] is False


class TestTwoKbCrossDomain:
    """双库跨域检索 — 两库 chunk 均出现，各自带 kb_name。"""

    def test_two_kbs_both_have_hits(
        self, client: TestClient, mock_retrieve_uc: AsyncMock
    ):
        """双库 query，结果包含两个库的 chunk 且各自 kb_name 正确。"""
        mock_retrieve_uc.execute.return_value = _make_result(
            hits=[
                _make_hit("ch_a1", kb_id="kb_a", kb_name="法律库", score=0.95),
                _make_hit("ch_b1", kb_id="kb_b", kb_name="金融库", score=0.91),
                _make_hit("ch_a2", kb_id="kb_a", kb_name="法律库", score=0.85),
            ],
            total=3,
            vector_count=40,
            bm25_count=40,
            fused_count=3,
        )

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "合同纠纷如何处理",
                "kb_ids": ["kb_a", "kb_b"],
                "top_k": 10,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["kb_ids"] == ["kb_a", "kb_b"]
        hits = data["data"]["hits"]
        assert len(hits) == 3

        # 验证每个 hit 都有 kb_name
        kb_names = {h["kb_name"] for h in hits}
        assert kb_names == {"法律库", "金融库"}

        # 验证 kb_a 的 hit 均带"法律库"
        kb_a_hits = [h for h in hits if h["kb_id"] == "kb_a"]
        assert all(h["kb_name"] == "法律库" for h in kb_a_hits)

        # 验证 meta
        meta = data["data"]["meta"]
        assert meta["multi_kb"] is True
        assert meta["kb_count"] == 2
        assert meta["fusion"] == "rrf"
        assert meta["rrf_k"] == 60

    def test_two_kbs_one_empty(self, client: TestClient, mock_retrieve_uc: AsyncMock):
        """一个库有结果一个库空 — 仅返回有结果的库的 chunk。"""
        mock_retrieve_uc.execute.return_value = _make_result(
            hits=[
                _make_hit("ch_a1", kb_id="kb_a", kb_name="法律库", score=0.95),
            ],
            total=1,
            vector_count=20,
            bm25_count=20,
            fused_count=1,
        )

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "查询",
                "kb_ids": ["kb_a", "kb_b"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        hits = data["data"]["hits"]
        assert len(hits) == 1
        assert hits[0]["kb_name"] == "法律库"
        assert data["data"]["meta"]["multi_kb"] is True
        assert data["data"]["meta"]["kb_count"] == 2


class TestFreePlanRejectsTwoKbs:
    """Free 套餐限制 — 传 2 库返回 20013 FEATURE_NOT_ALLOWED。"""

    def test_free_plan_with_two_kbs(
        self, free_plan_client: TestClient, mock_retrieve_uc: AsyncMock
    ):
        """free 租户传 2 库 → 403 + code 20013。"""
        resp = free_plan_client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "kb_ids": ["kb_1", "kb_2"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 403
        data = resp.json()
        assert data["code"] == 20013
        assert "最多支持 1 个库" in data["message"]
        mock_retrieve_uc.execute.assert_not_called()

    def test_free_plan_single_kb_allowed(
        self, free_plan_client: TestClient, mock_retrieve_uc: AsyncMock
    ):
        """free 套餐传 1 库正常放行（需 speed profile，balanced 不在 free 允许列表）。"""
        mock_retrieve_uc.execute.return_value = _make_result(
            hits=[_make_hit("ch1", kb_id="kb_1", kb_name="KB1")],
            total=1,
        )

        resp = free_plan_client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "kb_ids": ["kb_1"],
                "top_k": 5,
                "profile": "speed",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["meta"]["multi_kb"] is False

    def test_standard_plan_allows_three(self, mock_retrieve_uc: AsyncMock):
        """standard 套餐最多支持 3 库联合检索。"""
        app = _build_app(mock_retrieve_uc, plan="standard")
        client = TestClient(app, raise_server_exceptions=False)

        mock_retrieve_uc.execute.return_value = _make_result(total=0)

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "kb_ids": ["kb_1", "kb_2", "kb_3"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 200

    def test_standard_plan_rejects_four(self, mock_retrieve_uc: AsyncMock):
        """standard 套餐传 4 库 → 20013。"""
        app = _build_app(mock_retrieve_uc, plan="standard")
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "kb_ids": ["kb_1", "kb_2", "kb_3", "kb_4"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 403
        data = resp.json()
        assert data["code"] == 20013


class TestCrossTenantKbReturnsForbidden:
    """跨租户 KB — 其他租户的 KB ID → FORBIDDEN (10201)。

    注意: 实现返回的是 FORBIDDEN (10201, 403)，而非 brief 中提及的 NOT_FOUND (10300, 404)。
    这是因为 validate_kb_ownership 校验的是租户归属，而非资源存在性。
    """

    def test_cross_tenant_kb_raises_forbidden(
        self, client: TestClient, mock_retrieve_uc: AsyncMock
    ):
        """跨租户 KB → 403 + code 10201。"""
        mock_retrieve_uc.execute.side_effect = AppError(
            ErrorCode.FORBIDDEN,
            "知识库不属于当前租户: kb_cross",
        )

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "kb_ids": ["kb_cross"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 403
        data = resp.json()
        assert data["code"] == 10201
        assert "不属于当前租户" in data["message"]
        mock_retrieve_uc.execute.assert_awaited_once()

    def test_mixed_owned_and_cross_tenant(
        self, client: TestClient, mock_retrieve_uc: AsyncMock
    ):
        """自己的 KB + 别人的 KB → 整体失败 (403 FORBIDDEN)。"""
        mock_retrieve_uc.execute.side_effect = AppError(
            ErrorCode.FORBIDDEN,
            "知识库不属于当前租户: kb_other",
        )

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "kb_ids": ["kb_my", "kb_other"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 403
        data = resp.json()
        assert data["code"] == 10201


class TestNonexistentKbFails:
    """不存在的 KB ID — 返回 NOT_FOUND (10300, 404)。"""

    def test_nonexistent_kb(self, client: TestClient, mock_retrieve_uc: AsyncMock):
        """不存在的 KB ID → 404 + code 10300。"""
        mock_retrieve_uc.execute.side_effect = AppError(
            ErrorCode.NOT_FOUND,
            "知识库不存在: kb_nonexistent",
        )

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "kb_ids": ["kb_nonexistent"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 404
        data = resp.json()
        assert data["code"] == 10300
        assert "知识库不存在" in data["message"]

    def test_mixed_existing_and_nonexistent(
        self, client: TestClient, mock_retrieve_uc: AsyncMock
    ):
        """已有的 + 不存在的 → 整体失败 (404 NOT_FOUND)。"""
        mock_retrieve_uc.execute.side_effect = AppError(
            ErrorCode.NOT_FOUND,
            "知识库不存在: kb_nonexistent",
        )

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "kb_ids": ["kb_my", "kb_nonexistent"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 404
        data = resp.json()
        assert data["code"] == 10300


class TestQuotaCountedOnce:
    """配额计数 — 双库检索仅计 1 次配额。"""

    def test_two_kbs_counts_once(self, mock_retrieve_uc: AsyncMock):
        """双库检索中 record_retrieve_success 仅调用 1 次。"""
        mock_rate_limiter = AsyncMock()
        mock_rate_limiter.check_retrieve = AsyncMock()
        mock_rate_limiter.record_retrieve_success = AsyncMock()

        app = _build_app(
            mock_retrieve_uc,
            plan="pro",
            rate_limiter=mock_rate_limiter,
        )
        client = TestClient(app, raise_server_exceptions=False)

        mock_retrieve_uc.execute.return_value = _make_result(
            hits=[_make_hit("ch1", kb_id="kb_a", kb_name="KB A")],
            total=1,
        )

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "kb_ids": ["kb_a", "kb_b"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 200
        # 双库检索仅计 1 次
        mock_rate_limiter.check_retrieve.assert_awaited_once()
        mock_rate_limiter.record_retrieve_success.assert_awaited_once()

    def test_single_kb_counts_once(self, mock_retrieve_uc: AsyncMock):
        """单库检索 record_retrieve_success 调用 1 次（基线）。"""
        mock_rate_limiter = AsyncMock()
        mock_rate_limiter.check_retrieve = AsyncMock()
        mock_rate_limiter.record_retrieve_success = AsyncMock()

        app = _build_app(
            mock_retrieve_uc,
            plan="pro",
            rate_limiter=mock_rate_limiter,
        )
        client = TestClient(app, raise_server_exceptions=False)

        mock_retrieve_uc.execute.return_value = _make_result(
            hits=[_make_hit("ch1", kb_id="kb_a")],
            total=1,
        )

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "kb_ids": ["kb_a"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 200
        mock_rate_limiter.check_retrieve.assert_awaited_once()
        mock_rate_limiter.record_retrieve_success.assert_awaited_once()

    def test_qps_limit_blocks_before_execute(self, mock_retrieve_uc: AsyncMock):
        """QPS 限流拦截时不调用 execute。"""
        mock_rate_limiter = AsyncMock()
        mock_rate_limiter.check_retrieve = AsyncMock(
            side_effect=AppError(ErrorCode.API_RATE_LIMIT, "QPS 超限")
        )

        app = _build_app(
            mock_retrieve_uc,
            plan="pro",
            rate_limiter=mock_rate_limiter,
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "kb_ids": ["kb_a"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 429
        mock_rate_limiter.check_retrieve.assert_awaited_once()
        mock_retrieve_uc.execute.assert_not_called()


class TestResponseMetaMultiKb:
    """响应 meta 字段 — multi_kb/kb_count/fusion/rrf_k/per_kb_top_k。"""

    def test_meta_single_kb(self, client: TestClient, mock_retrieve_uc: AsyncMock):
        """单库 meta: multi_kb=false, kb_count=1, fusion=rrf。"""
        mock_retrieve_uc.execute.return_value = _make_result(total=0)

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "查询",
                "kb_ids": ["kb_a"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 200
        meta = resp.json()["data"]["meta"]
        assert meta["multi_kb"] is False
        assert meta["kb_count"] == 1
        assert meta["fusion"] == "rrf"
        assert meta["rrf_k"] == 60
        assert "per_kb_top_k" in meta
        assert meta["per_kb_top_k"] >= 10

    def test_meta_two_kbs(self, client: TestClient, mock_retrieve_uc: AsyncMock):
        """双库 meta: multi_kb=true, kb_count=2。"""
        mock_retrieve_uc.execute.return_value = _make_result(total=0)

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "查询",
                "kb_ids": ["kb_a", "kb_b"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 200
        meta = resp.json()["data"]["meta"]
        assert meta["multi_kb"] is True
        assert meta["kb_count"] == 2
        assert meta["fusion"] == "rrf"
        assert meta["rrf_k"] == 60

    def test_meta_three_kbs(self, client: TestClient, mock_retrieve_uc: AsyncMock):
        """三库 meta: multi_kb=true, kb_count=3。"""
        mock_retrieve_uc.execute.return_value = _make_result(total=0)

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "查询",
                "kb_ids": ["kb_a", "kb_b", "kb_c"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 200
        meta = resp.json()["data"]["meta"]
        assert meta["multi_kb"] is True
        assert meta["kb_count"] == 3

    def test_meta_custom_rrf_k(self, client: TestClient, mock_retrieve_uc: AsyncMock):
        """自定义 rrf_k=30 → meta.rrf_k=30。"""
        mock_retrieve_uc.execute.return_value = _make_result(total=0)

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "查询",
                "kb_ids": ["kb_a", "kb_b"],
                "top_k": 5,
                "rrf_k": 30,
            },
        )

        assert resp.status_code == 200
        meta = resp.json()["data"]["meta"]
        assert meta["rrf_k"] == 30

    def test_meta_tenant_policy(self, client: TestClient, mock_retrieve_uc: AsyncMock):
        """meta.tenant_policy 包含 plan + profile + 生效参数。"""
        mock_retrieve_uc.execute.return_value = _make_result(total=0)

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "查询",
                "kb_ids": ["kb_a"],
                "top_k": 5,
                "profile": "speed",
            },
        )

        assert resp.status_code == 200
        policy = resp.json()["data"]["meta"]["tenant_policy"]
        assert policy["plan"] == "pro"
        assert policy["retrieve_profile"] == "speed"
        assert policy["effective_mode"] == "vector"

    def test_meta_degraded_info(self, client: TestClient, mock_retrieve_uc: AsyncMock):
        """降级时 meta 包含 degraded 标记。"""
        mock_retrieve_uc.execute.return_value = _make_result(
            hits=[_make_hit("ch1", kb_id="kb_a", kb_name="KB A")],
            total=1,
            degraded=True,
            degraded_reason="BM25 索引暂不可用",
            degraded_kb_ids=["kb_b"],
        )

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "查询",
                "kb_ids": ["kb_a", "kb_b"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 200
        meta = resp.json()["data"]["meta"]
        assert meta["degraded"] is True
        assert meta["degraded_reason"] == "BM25 索引暂不可用"


class TestRequestValidationEdgeCases:
    """请求体校验边界 — 空 kb_ids、超限等。"""

    def test_empty_kb_ids(self, client: TestClient, mock_retrieve_uc: AsyncMock):
        """空 kb_ids [] → 通过 Pydantic 但 router 调用 execute 后处理。"""
        mock_retrieve_uc.execute.return_value = _make_result(
            hits=[],
            total=0,
        )

        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "kb_ids": [],
                "top_k": 5,
            },
        )

        # 空 kb_ids 通过 Pydantic 校验（无 min_length），
        # router 一并转发给 use case 处理。
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["kb_ids"] == []
        assert data["data"]["meta"]["kb_count"] == 0

    def test_missing_kb_ids(self, client: TestClient):
        """缺少 kb_ids → 422。"""
        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "top_k": 5,
            },
        )

        assert resp.status_code == 422

    def test_missing_query(self, client: TestClient):
        """缺少 query → 422。"""
        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "kb_ids": ["kb_a"],
                "top_k": 5,
            },
        )

        assert resp.status_code == 422

    def test_top_k_negative(self, client: TestClient):
        """top_k < 1 → 422。"""
        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "kb_ids": ["kb_a"],
                "top_k": 0,
            },
        )

        assert resp.status_code == 422

    def test_top_k_exceeds_max(self, client: TestClient):
        """top_k > 50 → 422。"""
        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "测试查询",
                "kb_ids": ["kb_a"],
                "top_k": 51,
            },
        )

        assert resp.status_code == 422
