# Task 3.3

### 3.3 feedback_service
- **目标**: 校验归属（查 retrieval_logs 验证 tenant 匹配 + trace_id 一致）→ Langfuse SDK create_score → 返回 feedback_id
- **文件**: `src/ragnexus/services/feedback_service.py`
- **要点**: 复用 get_langfuse_client()，不重复创建 client；score name="user_feedback"
- **依赖**: 1.5, 2.4, 3.1, 3.2
- **验证**: 单元测试 4 场景
- **预估**: 45min


## TDD
写测试先于实现。RED → GREEN → 提交。