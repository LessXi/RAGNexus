# Task 2.2

## Requirements

### 2.2 log_id 预生成 + 响应字段 + 数据流
- **目标**: 用 nanoid 生成 log_id，透传到 UC → log_port → retrieval_logs，响应 metadata 加 log_id + trace_id
- **文件**: `retrieve_router.py`, `retrieve_use_case.py`（log_id 参数透传）
- **要点**: router 生成 `"log_" + nanoid(12)` → 传入 `uc.execute(log_id=...)` → UC 传入 `log_port.log(log_id=...)`；log_port 接口新增 log_id 参数
- **依赖**: 2.1
- **验证**: 响应含非空 log_id，DB 中 log_id 匹配
- **预估**: 30min


## TDD
写测试先于实现。RED → GREEN → 提交。