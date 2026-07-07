# Task 3.2

### 3.2 feedback schema
- **目标**: FeedbackRequest（trace_id必填/log_id建议/score 1~5/comment可选）+ FeedbackData（feedback_id/trace_id/log_id/score）
- **文件**: `src/ragnexus/schemas/feedback.py`
- **依赖**: 无
- **验证**: Pydantic 校验通过
- **预估**: 15min


## TDD
写测试先于实现。RED → GREEN → 提交。