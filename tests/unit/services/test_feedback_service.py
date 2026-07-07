"""FeedbackService 单元测试 —— 4 种场景全覆盖。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.schemas.feedback import FeedbackRequest
from ragnexus.services.feedback_service import FeedbackService

# ============================================================================
# 辅助 mock
# ============================================================================


class _CtxAcquirer:
    """asyncpg.Pool.acquire() 的 async context manager mock。"""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


def _make_pool(fetchrow_result):
    """构造 mock asyncpg.Pool，其 acquire 返回 _CtxAcquirer。"""
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_result)
    pool.acquire.return_value = _CtxAcquirer(conn)
    return pool


def _make_langfuse(enabled=True, create_score_return="score_abc123"):
    """构造 mock RetrieveObservability。"""
    lf = MagicMock()
    lf.enabled = enabled
    lf.create_score = MagicMock(return_value=create_score_return)
    return lf


def _make_request(score=5, log_id="log_001", trace_id="trace_xyz"):
    return FeedbackRequest(trace_id=trace_id, log_id=log_id, score=score)


# ============================================================================
# 测试
# ============================================================================


class TestSubmitFeedbackNormal:
    """正常流程：tenant 匹配 + trace_id 一致 + Langfuse 正常。"""

    @pytest.mark.asyncio
    async def test_normal_feedback_returns_feedback_id(self):
        """正常提交反馈应返回 feedback_id。"""
        pool = _make_pool({"tenant_id": "t1", "trace_id": "trace_xyz"})
        lf = _make_langfuse()
        svc = FeedbackService(pool, lf)
        req = _make_request()

        result = await svc.submit_feedback("t1", req)

        assert result.feedback_id == "score_abc123"
        assert result.trace_id == "trace_xyz"
        assert result.log_id == "log_001"
        assert result.score == 5
        lf.create_score.assert_called_once_with(
            trace_id="trace_xyz",
            name="user_feedback",
            value=5.0,
            comment=None,
        )


class TestSubmitFeedbackLangfuseUnavailable:
    """Langfuse 不可用场景 → 抛 FEEDBACK_SERVICE_UNAVAILABLE (20020)。"""

    @pytest.mark.asyncio
    async def test_langfuse_disabled_raises_20020(self):
        """langfuse_client.enabled=False 时抛 20020。"""
        pool = _make_pool({"tenant_id": "t1", "trace_id": "trace_xyz"})
        lf = _make_langfuse(enabled=False)
        svc = FeedbackService(pool, lf)
        req = _make_request()

        with pytest.raises(AppError) as exc_info:
            await svc.submit_feedback("t1", req)

        assert exc_info.value.code == ErrorCode.FEEDBACK_SERVICE_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_create_score_returns_none_raises_20020(self):
        """create_score 返回 None（写入失败）时抛 20020。"""
        pool = _make_pool({"tenant_id": "t1", "trace_id": "trace_xyz"})
        lf = _make_langfuse(enabled=True, create_score_return=None)
        svc = FeedbackService(pool, lf)
        req = _make_request()

        with pytest.raises(AppError) as exc_info:
            await svc.submit_feedback("t1", req)

        assert exc_info.value.code == ErrorCode.FEEDBACK_SERVICE_UNAVAILABLE


class TestSubmitFeedbackUnauthorized:
    """无权场景 → 抛 FEEDBACK_UNAUTHORIZED (20021)。"""

    @pytest.mark.asyncio
    async def test_log_id_not_found_raises_20021(self):
        """log_id 不存在时抛 20021。"""
        pool = _make_pool(None)  # fetchrow 返回 None
        lf = _make_langfuse()
        svc = FeedbackService(pool, lf)
        req = _make_request()

        with pytest.raises(AppError) as exc_info:
            await svc.submit_feedback("t1", req)

        assert exc_info.value.code == ErrorCode.FEEDBACK_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_tenant_id_mismatch_raises_20021(self):
        """tenant_id 不匹配时抛 20021。"""
        pool = _make_pool(
            {"tenant_id": "other_tenant", "trace_id": "trace_xyz"},
        )
        lf = _make_langfuse()
        svc = FeedbackService(pool, lf)
        req = _make_request()

        with pytest.raises(AppError) as exc_info:
            await svc.submit_feedback("t1", req)  # t1 ≠ other_tenant

        assert exc_info.value.code == ErrorCode.FEEDBACK_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_trace_id_mismatch_raises_20021(self):
        """trace_id 与日志记录不一致时抛 20021。"""
        pool = _make_pool({"tenant_id": "t1", "trace_id": "different_trace"})
        lf = _make_langfuse()
        svc = FeedbackService(pool, lf)
        req = _make_request()  # trace_id="trace_xyz" ≠ "different_trace"

        with pytest.raises(AppError) as exc_info:
            await svc.submit_feedback("t1", req)

        assert exc_info.value.code == ErrorCode.FEEDBACK_UNAUTHORIZED


class TestSubmitFeedbackInvalidScore:
    """评分越界场景 → 抛 FEEDBACK_INVALID_SCORE (20022)。"""

    @pytest.mark.asyncio
    async def test_score_too_low_raises_20022(self):
        """score < 1 时抛 20022 — 绕过 Pydantic 校验的防御性检查。"""
        pool = _make_pool({"tenant_id": "t1", "trace_id": "trace_xyz"})
        lf = _make_langfuse()
        svc = FeedbackService(pool, lf)
        req = FeedbackRequest.model_construct(
            trace_id="trace_xyz", log_id="log_001", score=0
        )

        with pytest.raises(AppError) as exc_info:
            await svc.submit_feedback("t1", req)

        assert exc_info.value.code == ErrorCode.FEEDBACK_INVALID_SCORE

    @pytest.mark.asyncio
    async def test_score_too_high_raises_20022(self):
        """score > 5 时抛 20022 — 绕过 Pydantic 校验的防御性检查。"""
        pool = _make_pool({"tenant_id": "t1", "trace_id": "trace_xyz"})
        lf = _make_langfuse()
        svc = FeedbackService(pool, lf)
        req = FeedbackRequest.model_construct(
            trace_id="trace_xyz", log_id="log_001", score=6
        )

        with pytest.raises(AppError) as exc_info:
            await svc.submit_feedback("t1", req)

        assert exc_info.value.code == ErrorCode.FEEDBACK_INVALID_SCORE
