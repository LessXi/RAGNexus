"""用户反馈相关 Pydantic 模型。"""

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    """用户反馈请求。"""

    model_config = {"extra": "ignore"}

    trace_id: str = Field(..., description="Langfuse trace ID，必填")
    log_id: str | None = Field(None, description="检索日志 ID，建议提供")
    score: int = Field(..., description="评分 1~5")
    comment: str | None = Field(None, max_length=1000, description="备注，可选")


class FeedbackData(BaseModel):
    """反馈数据响应。"""

    model_config = {"extra": "ignore"}

    feedback_id: str = Field(..., description="Langfuse 返回的 feedback ID")
    trace_id: str = Field(..., description="关联的 trace ID")
    log_id: str | None = Field(None, description="关联的日志 ID")
    score: int = Field(..., description="评分")
