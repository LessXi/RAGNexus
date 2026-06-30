## 架构总览

```
src/ragnexus/
├── core/                          # 新建包
│   ├── __init__.py
│   ├── logger.py                  # 日志工具类 + 装饰器 + 连接池代理 + 上下文适配器
│   └── errors.py                  # ErrorCode 枚举 + AppError 异常类 + raise_error() 快捷函数
├── domain/
│   └── errors.py                  # 删除原有内容，改为从 core 重新导出
├── adapters/http/
│   ├── middleware.py               # 新增：API 日志中间件
│   └── error_handlers.py          # 小幅调整：新增全局兜底异常处理器
├── config.py                       # 新增 4 个配置项字段
└── composition.py                  # basicConfig → setup_logging() + 注册中间件 + 连接池包一层
```

## 日志系统

### 格式模板

```
{时间} | {级别:8} | {模块}:{函数}:{行号} | {事件类型} | [条件字段] | {键=值 ...}
```

条件字段（`req_id`、`user_id`、`client_ip`）由中间件通过 ContextVar 注入，仅在有请求上下文时出现。

### 七种事件类型

| 类型 | 级别 | 触发条件 |
|------|------|---------|
| `API_REQUEST` | INFO | 每个请求进入时 |
| `API_RESPONSE` | INFO | 每个请求返回时（含异常路径，由中间件统一记录） |
| `MODEL_REQUEST` | INFO | 调用模型之前 |
| `MODEL_RESPONSE` | INFO | 模型返回之后（失败路径通过 `error=` 字段标记） |
| `DB_QUERY` | DEBUG | 仅在 `LOG_LEVEL=DEBUG` 时输出 |
| `SYSTEM_ERROR` | ERROR | 未捕获的系统异常 |
| `BIZ_EVENT` | INFO | 业务关键节点（限三类：用户可感知结果、外部副作用、状态转换） |

### 输出目标

| 目标 | 特性 |
|------|------|
| 控制台 | 彩色输出（colorlog），全级别，500 字符截断，不做 repr() 包裹 |
| `logs/YYYY-MM-DD/app.log` | 全级别，不截断，repr() 包裹特殊字符，单文件 10MB 滚动，保留 30 天 |
| `logs/YYYY-MM-DD/error.log` | 仅 ERROR 及以上级别，其余同上 |

### 性能方案

- **异步安全**：`QueueHandler` + 后台 `QueueListener` 线程（与 uvicorn 内部方案一致）。主线程只把日志推入内存队列后立即返回。
- **队列容量**：5000 条上限，满时丢弃最旧日志（永不阻塞业务）。
- **惰性求值**：所有 DEBUG 级别日志使用 `%s` 占位符，不用 f-string，避免级别不够时仍执行参数计算。

### 实现组件

1. **日志中间件**（`adapters/http/middleware.py`）：请求进入时记录 `API_REQUEST`，对 JSON 请求体读取并回填（multipart 跳过），调用路由后记录 `API_RESPONSE`（含状态码和耗时）。
2. **@log_model_call 装饰器**（`core/logger.py`）：包装 async 函数，自动计时，记录 `MODEL_REQUEST`/`MODEL_RESPONSE`，异常路径同样处理。
3. **LoggedPool 连接池代理**（`core/logger.py`）：包装 asyncpg 连接池，拦截 `fetch`/`fetchrow`/`fetchval`/`execute` 四个方法，自动记录 `DB_QUERY`（含操作类型、表名、耗时、行数）。
4. **ContextAdapter 上下文适配器**（`core/logger.py`）：继承 `LoggerAdapter`，从 `ContextVar` 读取请求上下文字段，与调用方传入的 `extra` 字段合并。
5. **全局异常兜底**（`error_handlers.py`）：catch-all handler 捕获未处理的异常，记录 `SYSTEM_ERROR`（含完整堆栈）。

### 配置项

| 配置键 | 默认值 | 用途 |
|--------|--------|------|
| `LOG_LEVEL` | INFO | 日志级别（已有） |
| `LOG_DIR` | logs | 日志根目录 |
| `LOG_QUEUE_SIZE` | 5000 | 异步队列容量上限 |
| `LOG_CONSOLE_MAX_LENGTH` | 500 | 控制台字段截断长度 |
| `LOG_MODEL_CONTENT` | true | 是否将模型交互文本写入日志 |

## 错误码系统

### 区间分类

| 区间 | 用途 |
|------|------|
| `0` | 成功 |
| `10001~10199` | 参数校验 |
| `10200~10299` | 认证与鉴权 |
| `10300~10399` | 资源操作 |
| `10400~10499` | 文件与媒体 |
| `10500~10599` | 上游服务 |
| `20000~20999` | 接口与 HTTP |
| `30000~30999` | 数据库与存储 |
| `40000~40999` | 模型调用（LLM/嵌入） |
| `50000~50999` | 系统与服务 |

### 数据结构

```python
class ErrorCode(Enum):
    SUCCESS = (0, 200, "成功")
    PARAM_ERROR = (10001, 422, "参数错误")
    # ... 40+ 条

class AppError(Exception):
    def __init__(self, code: ErrorCode, message: str | None = None, errors: list[dict] | None = None):
        ...
```

每条 ErrorCode 成员是一个 `(数字码, HTTP状态码, 对外提示)` 三元组。

### 抛出方式

```python
raise AppError(ErrorCode.PARAM_ERROR, "自定义消息", errors=[...])
raise AppError(ErrorCode.MODEL_TIMEOUT)
```

### 迁移方案

现有调用代码从：
```python
raise ValidationError("参数错误", errors=[...])      # 旧写法
```
改为：
```python
raise AppError(ErrorCode.PARAM_ERROR, "参数错误", errors=[...])  # 新写法
```

`error_handlers.py` 不做修改——它读取 `exc.code`/`exc.http_status`/`exc.message`，`AppError` 完整提供这三个属性。

### 快捷抛错

```python
# 一行抛错
raise_error(ErrorCode.MODEL_TIMEOUT)
# 等价于: raise AppError(ErrorCode.MODEL_TIMEOUT)
```
