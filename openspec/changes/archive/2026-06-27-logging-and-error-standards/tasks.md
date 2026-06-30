## 实施任务

### 阶段一：基础 — 错误码系统

- [x] 创建 `core/errors.py` — ErrorCode 枚举（40+ 条目）+ AppError 异常类 + raise_error() 快捷函数
- [x] 更新 `domain/errors.py` — 删除 9 个子类，改为从 core 重新导出 AppError
- [x] 迁移全部抛异常位置（15+ 处，跨 6 个文件），从 `raise ValidationError(...)` 改为 `raise AppError(ErrorCode.PARAM_ERROR, ...)`
- [x] 更新 `tests/unit/domain/test_errors.py` — 适配新 ErrorCode 枚举值
- [x] 运行测试验证错误码迁移

### 阶段二：日志核心

- [x] 在 pyproject.toml 中添加 `colorlog` 依赖
- [x] 在 `config.py` 中新增配置字段（LOG_DIR, LOG_QUEUE_SIZE, LOG_CONSOLE_MAX_LENGTH, LOG_MODEL_CONTENT）
- [x] 更新 `.env.example`，补充新配置键
- [x] 创建 `core/__init__.py`
- [x] 创建 `core/logger.py` — setup_logging()、ContextAdapter 上下文适配器、LoggedPool 连接池代理、@log_model_call 装饰器
- [x] 将 `composition.py` lifespan 中的 `logging.basicConfig` 替换为 `setup_logging()`

### 阶段三：请求日志

- [x] 创建 `adapters/http/middleware.py` — LoggingMiddleware（生成 req_id、注入 ContextVar、记录 API_REQUEST + API_RESPONSE）
- [x] 在 `composition.py` 的 build_app() 中注册 LoggingMiddleware
- [x] 实现请求体读取/回填逻辑（JSON 请求读取，multipart 跳过）

### 阶段四：模型日志

- [x] 在 `adapters/embedder/openai_compat.py` 的 `OpenAICompatEmbedder.embed()` 上添加 `@log_model_call` 装饰器

### 阶段五：数据库日志

- [x] 在 `composition.py` lifespan 中用 LoggedPool 代理包装 asyncpg 连接池

### 阶段六：全局异常 + 业务日志

- [x] 在 `error_handlers.py` 中添加全局 catch-all handler，记录 SYSTEM_ERROR 日志
- [x] 在 use_case 文件的关键业务节点添加 BIZ_EVENT 日志（upload_doc、create_kb、retrieve）

### 阶段七：验证

- [x] 编写 `tests/unit/core/test_logger.py` — 验证格式、队列、滚动配置
- [x] 编写 `tests/unit/core/test_errors.py` — 验证全部 ErrorCode 值和 AppError 字段
- [x] 运行已有集成测试，验证无功能回归
- [x] 肉眼检查：启动服务，触发每种事件类型，验证日志输出格式
