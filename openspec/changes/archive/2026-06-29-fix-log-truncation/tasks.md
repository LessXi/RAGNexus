## 1. 移除 log_model_call 中的硬编码截断

- [x] 1.1 移除 `logger.py` 中 `log_model_call` 装饰器内 prompt 的 `[:200] + "..."` 截断
- [x] 1.2 移除 `logger.py` 中 `log_model_call` 装饰器内 response 的 `[:200] + "..."` 截断

## 2. 恢复中间件请求体日志记录

- [x] 2.1 在 `middleware.py` 的 API_REQUEST 日志 extra 中添加 `body` 字段（JSON 请求体内容）
