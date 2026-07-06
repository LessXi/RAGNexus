"""FeedbackService — 用户反馈收集服务。

提交反馈流程：
1. 通过 retrieve_logs 校验租户归属
2. 验证 trace_id 一致性
3. 通过 Langfuse SDK 写 score
4. 返回 feedback_id

四种场景处理：
- 正常: tenant 匹配 + trace_id 一致 + Langfuse 正常 → 返回 feedback_id
- 20020 Langfuse 不可用: langfuse_client.enabled=False 或 score 写入失败
- 20021 无权: log_id 不存在或 tenant_id 不匹配
- 20022 评分越界: score 超出 1~5 范围（防御性检查）
"""

from __future__ import annotations

import logging

import asyncpg

from ragnexus.core.errors import ErrorCode, raise_error
from ragnexus.observability.langfuse_client import RetrieveObservability
from ragnexus.schemas.feedback import FeedbackData, FeedbackRequest

logger = logging.getLogger(__name__)


class FeedbackService:
    """用户反馈收集服务。

    校验租户归属后将用户评分写入 Langfuse。
    """

    def __init__(
        self, pool: asyncpg.Pool, langfuse_client: RetrieveObservability
    ) -> None:
        self._pool = pool
        self._langfuse = langfuse_client

    async def submit_feedback(
        self, tenant_id: str, request: FeedbackRequest
    ) -> FeedbackData:
        """提交用户反馈。

        Args:
            tenant_id: 当前租户 ID
            request: 反馈请求（含 trace_id、log_id、score、comment）

        Returns:
            FeedbackData: 含 feedback_id 的响应数据

        Raises:
            AppError: 20020 Langfuse 不可用 / 20021 无权 / 20022 评分越界
        """
        # 防御性评分越界检查
        if not 1 <= request.score <= 5:
            raise_error(
                ErrorCode.FEEDBACK_INVALID_SCORE,
            )

        # 1. 校验租户归属
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT tenant_id, trace_id " "FROM retrieve_logs " "WHERE log_id=$1",
                request.log_id,
            )

        if row is None:
            raise_error(
                ErrorCode.FEEDBACK_UNAUTHORIZED,
                "未找到对应的检索日志",
            )

        db_tenant_id: str = row["tenant_id"] or ""
        db_trace_id: str = row["trace_id"] or ""

        if db_tenant_id != tenant_id:
            raise_error(
                ErrorCode.FEEDBACK_UNAUTHORIZED,
                "租户无权操作该反馈记录",
            )

        # 2. 验证 trace_id 一致
        if db_trace_id != request.trace_id:
            raise_error(
                ErrorCode.FEEDBACK_UNAUTHORIZED,
                "trace_id 与日志记录不一致",
            )

        # 3. 检查 Langfuse 是否可用
        if not self._langfuse.enabled:
            raise_error(
                ErrorCode.FEEDBACK_SERVICE_UNAVAILABLE,
            )

        # 4. 写 Langfuse score
        score_id = self._langfuse.create_score(
            trace_id=request.trace_id,
            name="user_feedback",
            value=float(request.score),
            comment=request.comment,
        )

        if score_id is None:
            raise_error(
                ErrorCode.FEEDBACK_SERVICE_UNAVAILABLE,
            )

        return FeedbackData(
            feedback_id=score_id,
            trace_id=request.trace_id,
            log_id=request.log_id,
            score=request.score,
        )
