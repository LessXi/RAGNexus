# 修复日志文件截断偏离设计

## 动机

日志系统设计文档明确规定：文件 Handler（`app.log` / `error.log`）**不截断**，仅控制台 Handler 在 500 字符处截断。但实际代码中存在两处提前截断，导致文件日志内容不完整，偏离设计。

## 目标

移除日志内容层面的提前截断，使文件日志输出与设计一致：全内容输出，不截断。

## 范围

- `src/ragnexus/core/logger.py`：移除 `log_model_call` 装饰器中 prompt/response 的硬编码 200 字符截断
- `src/ragnexus/adapters/http/middleware.py`：恢复 API_REQUEST 日志中的请求体内容记录

## 非范围

- 不改变控制台截断行为（仍由 `_TruncatingColoredFormatter` 在 500 字符处截断）
- 不新增配置项
- 不改变日志格式
