# Task 2.5

## Requirements

### 2.5 PgRetrieveLogRepository 适配
- **目标**: `log()` 方法接口新增 log_id + tenant_id + trace_id + profile + search_query + effective_query 参数，INSERT 写入所有新字段
- **文件**: `src/ragnexus/adapters/retrieve_log/pg.py`, `src/ragnexus/domain/ports.py`（RetrieveLogPort 接口扩展）
- **要点**: log_id 由 router 生成后传入，tenant_id 从 TenantContext 获取后传入；保持 try/catch + debug 日志的异常处理模式
- **依赖**: 2.4
- **验证**: 单元测试验证所有新字段被写入
- **预估**: 20min


## TDD
写测试先于实现。RED → GREEN → 提交。