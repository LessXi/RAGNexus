"""RateLimitService 单元测试 —— Redis QPS + 日配额限流。"""

from unittest.mock import AsyncMock, MagicMock
import pytest
from ragnexus.services.rate_limit_service import RateLimitService
from ragnexus.core.errors import AppError, ErrorCode


class TestCheckRetrieve:
    """check_retrieve: QPS 限流 + 日配额检查。"""

    @pytest.fixture
    def redis_mock(self):
        """构造一个支持 incr/get/expire 的 mock Redis。"""
        mock = AsyncMock()
        mock.incr = AsyncMock(return_value=1)
        mock.get = AsyncMock(return_value=None)
        mock.expire = AsyncMock(return_value=True)
        return mock

    @pytest.mark.asyncio
    async def test_qps_exceeded_raises_app_error(self, redis_mock):
        """QPS 超过 free 套餐的 retrieve_qps=3 时抛 API_RATE_LIMIT。"""
        redis_mock.incr = AsyncMock(return_value=4)  # 第 4 次请求超限
        svc = RateLimitService(redis_mock)

        with pytest.raises(AppError) as exc_info:
            await svc.check_retrieve("t1", "free")
        assert exc_info.value.code == ErrorCode.API_RATE_LIMIT
        assert "QPS" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_daily_quota_exceeded_raises_app_error(self, redis_mock):
        """日配额已达上限时抛 QUOTA_EXCEEDED。"""
        redis_mock.get = AsyncMock(return_value=500)  # free=500 每日
        svc = RateLimitService(redis_mock)

        with pytest.raises(AppError) as exc_info:
            await svc.check_retrieve("t2", "free")
        assert exc_info.value.code == ErrorCode.QUOTA_EXCEEDED
        assert "日检索" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_within_limits_passes(self, redis_mock):
        """QPS 和日配额均在范围内时正常通过。"""
        svc = RateLimitService(redis_mock)

        # 不应抛异常
        await svc.check_retrieve("t3", "pro")

    @pytest.mark.asyncio
    async def test_qps_key_has_correct_format(self, redis_mock):
        """验证 Redis key 格式正确：rag:ratelimit:retrieve:{tid}:{unix_sec}。"""
        svc = RateLimitService(redis_mock)

        await svc.check_retrieve("t-abc", "standard")
        # 检查 incr 被调用且 key 符合格式
        assert redis_mock.incr.called
        key = redis_mock.incr.call_args[0][0]
        assert key.startswith("rag:ratelimit:retrieve:t-abc:")
        # key 末尾应为 Unix 秒级时间戳 (10 位)
        suffix = key.split(":")[-1]
        assert len(suffix) == 10
        assert suffix.isdigit()

    @pytest.mark.asyncio
    async def test_qps_first_request_sets_expire(self, redis_mock):
        """第一次请求 (count==1) 时设置 2 秒 TTL。"""
        svc = RateLimitService(redis_mock)

        await svc.check_retrieve("t4", "free")
        assert redis_mock.expire.called
        key, ttl = redis_mock.expire.call_args[0]
        assert ttl == 2


class TestRecordRetrieveSuccess:
    """record_retrieve_success: 检索成功后日计数 +1。"""

    @pytest.fixture
    def redis_mock(self):
        mock = AsyncMock()
        mock.incr = AsyncMock(return_value=42)
        mock.expire = AsyncMock(return_value=True)
        return mock

    @pytest.mark.asyncio
    async def test_increments_daily_counter(self, redis_mock):
        svc = RateLimitService(redis_mock)

        await svc.record_retrieve_success("t5")
        assert redis_mock.incr.called
        key = redis_mock.incr.call_args[0][0]
        assert key.startswith("rag:quota:retrieve:daily:t5:")

    @pytest.mark.asyncio
    async def test_sets_25h_expire(self, redis_mock):
        svc = RateLimitService(redis_mock)

        await svc.record_retrieve_success("t6")
        assert redis_mock.expire.called
        _, ttl = redis_mock.expire.call_args[0]
        assert ttl == 25 * 3600  # 90000 秒


class TestGetDailyCount:
    """get_daily_count: 查询租户当日检索量。"""

    @pytest.fixture
    def redis_mock(self):
        mock = AsyncMock()
        mock.get = AsyncMock(return_value=None)
        return mock

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_data(self, redis_mock):
        svc = RateLimitService(redis_mock)

        count = await svc.get_daily_count("t7")
        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_stored_value(self, redis_mock):
        redis_mock.get = AsyncMock(return_value=128)
        svc = RateLimitService(redis_mock)

        count = await svc.get_daily_count("t8")
        assert count == 128
