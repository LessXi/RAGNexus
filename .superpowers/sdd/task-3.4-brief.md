# Task 3.4

### 3.4 feedback_router
- **目标**: POST /v1/rag/feedback，Depends(get_current_tenant)
- **文件**: `src/ragnexus/adapters/http/feedback_router.py`
- **依赖**: 3.3
- **验证**: curl 测试 4 场景
- **预估**: 30min


## TDD
写测试先于实现。RED → GREEN → 提交。