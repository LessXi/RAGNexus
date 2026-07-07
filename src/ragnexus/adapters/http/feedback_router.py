"""用户反馈路由 — POST /v1/rag/feedback。"""

from fastapi import APIRouter, Depends

from ragnexus.core.auth import TenantContext
from ragnexus.schemas.feedback import FeedbackData, FeedbackRequest
from ragnexus.services.feedback_service import FeedbackService


def create_router(
    get_current_tenant,
    feedback_service: FeedbackService,
) -> APIRouter:
    """返回含 POST /v1/rag/feedback 端点的 APIRouter。

    ``get_current_tenant`` 由 ``make_get_current_tenant`` 创建，注入
    ``Depends(get_current_tenant)`` 提取 TenantContext。
    ``feedback_service`` 由 lifespan 注入，处理反馈写入逻辑。
    """

    router = APIRouter(prefix="/v1/rag", tags=["feedback"])

    @router.post("/feedback", response_model=FeedbackData)
    async def submit_feedback(
        request: FeedbackRequest,
        current_tenant: TenantContext = Depends(get_current_tenant),  # noqa: B008
    ):
        """提交检索效果反馈。

        校验租户归属后，将用户评分通过 Langfuse 写入。
        错误场景由全局 error_handler 统一转换为 JSON 错误响应：
        - 20022: 评分超出 1~5 范围
        - 20021: log_id 不存在或租户无权操作
        - 20020: Langfuse 不可用或写入失败
        """
        return await feedback_service.submit_feedback(current_tenant.tenant_id, request)

    return router
