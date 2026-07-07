import time
from datetime import UTC, datetime

import redis.asyncio as aioredis

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.tenant.plan_presets import PLAN_PRESETS


class RateLimitService:
    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def check_retrieve(self, tenant_id: str, plan: str) -> None:
        """QPS 限流 + 日配额检查。超限抛 AppError。"""
        limits = PLAN_PRESETS[plan]["limits"]
        # QPS
        second = int(time.time())
        qps_key = f"rag:ratelimit:retrieve:{tenant_id}:{second}"
        qps_count = await self._redis.incr(qps_key)
        if qps_count == 1:
            await self._redis.expire(qps_key, 2)
        if qps_count > limits["retrieve_qps"]:
            raise AppError(
                ErrorCode.API_RATE_LIMIT,
                f"检索 QPS 超限（{limits['retrieve_qps']}/秒）",
            )
        # 日配额
        date_str = datetime.now(UTC).strftime("%Y%m%d")
        daily_key = f"rag:quota:retrieve:daily:{tenant_id}:{date_str}"
        daily_count = await self._redis.get(daily_key)
        if daily_count and int(daily_count) >= limits["retrieve_daily"]:
            raise AppError(
                ErrorCode.QUOTA_EXCEEDED,
                f"日检索量已达上限（{limits['retrieve_daily']}次/天）",
            )

    async def record_retrieve_success(self, tenant_id: str) -> None:
        """检索成功后日计数 +1。"""
        date_str = datetime.now(UTC).strftime("%Y%m%d")
        key = f"rag:quota:retrieve:daily:{tenant_id}:{date_str}"
        await self._redis.incr(key)
        await self._redis.expire(key, 25 * 3600)

    async def get_daily_count(self, tenant_id: str) -> int:
        """查询租户当日检索量（供 /auth/me 使用）。"""
        date_str = datetime.now(UTC).strftime("%Y%m%d")
        val = await self._redis.get(f"rag:quota:retrieve:daily:{tenant_id}:{date_str}")
        return int(val) if val else 0
