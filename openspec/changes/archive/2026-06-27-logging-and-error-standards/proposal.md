## 背景

RAGNexus 当前缺乏体系化日志（仅一行 `logging.basicConfig`）和统一错误码规范（9 个零散 DomainError 子类，code 1000~1600），导致线上问题排查依赖 ad-hoc 手段，未覆盖 LLM 调用、数据库查询等关键路径，错误码区间不匹配生产级 API 标准。

## 变更内容

### 日志改造
- 新增 `core/logger.py` — 统一日志工具：结构化格式、控制台彩色输出、文件按天/大小滚动、异步队列
- 新增 `adapters/http/middleware.py` — API 请求/响应日志中间件，自动记录每个请求的 method/path/status/cost_ms
- 新增 `@log_model_call` 装饰器 — 模型调用自动计时+入参+结果日志
- 引入 `colorlog` 依赖（纯 Python，15KB）
- 新增 `LOG_DIR`、`LOG_CONSOLE_MAX_LENGTH`、`LOG_MODEL_CONTENT`、`LOG_QUEUE_SIZE` 四个配置项

### 错误码改造 — **破坏性变更**
- 新增 `core/errors.py` — `ErrorCode` 枚举（40+ 码，覆盖 10001~50999）+ 统一 `AppError` 异常类
- 删除现有 `DomainError` 及其 9 个子类，改为 `AppError` 统一异常
- 现有 15+ 处 call site 从 `raise ValidationError(...)` 迁移为 `raise AppError(ErrorCode.PARAM_ERROR, ...)`
- `error_handlers.py` 基本不动（仍读 `exc.code`/`exc.http_status`）

## 能力清单

### 新增能力
- `logging-system`：结构化日志系统（控制台彩色+文件滚动+异步队列+7 种事件类型覆盖 API/模型/数据库/异常全路径）
- `error-code-system`：统一错误码体系（40+ 枚举码 + 标准区间 + AppError 统一异常）

### 修改能力
- `error-handling`：错误处理从 DomainError 类层级迁移到 ErrorCode 枚举 + AppError，`error_handlers.py` 接口不变但上游异常类型变更
