"""RAGNexus 日志系统核心模块。

提供：
- setup_logging(cfg) — 一键配置日志系统（QueueHandler + QueueListener + 彩色控制台 + 文件滚动）
- ContextAdapter — 自动注入 ContextVar 上下文字段
- set_log_context / clear_log_context — 请求级上下文管理
- @log_model_call — 自动记录模型调用事件
- LoggedPool — asyncpg.Pool 代理，记录 DB 查询事件
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import logging
import logging.handlers
import os
import queue
import re
import shutil
import time
from collections.abc import MutableMapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from colorlog import ColoredFormatter

from ragnexus.config import Settings, get_settings

# ---------------------------------------------------------------------------
# ContextVar — 请求级上下文字段注入
# ---------------------------------------------------------------------------

_log_ctx: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "log_ctx", default=None
)


def set_log_context(**kwargs: str) -> None:
    """由中间件调用，注入 req_id / user_id / client_ip 等上下文字段。

    示例::

        set_log_context(req_id="abc123", user_id="user1")
    """
    _log_ctx.set(kwargs)


def clear_log_context() -> None:
    """请求结束后清理上下文（重置为空字典）。"""
    _log_ctx.set({})


# ---------------------------------------------------------------------------
# ContextAdapter — 自动注入 LogRecord.extra
# ---------------------------------------------------------------------------


class ContextAdapter(logging.LoggerAdapter):
    """LoggerAdapter 子类，自动将 ContextVar 中的字段合并到 LogRecord.extra。

    同时构建 ``extra_fields`` 字符串供格式化模板引用，
    将上下文信息和事件结构化字段全部渲染为 key=value 格式。

    覆写 ``log()`` 自动注入真实调用方（跳过本模块栈帧），
    解决 LoggedPool / @log_model_call 等内部封装导致的 %(module)s 错误。
    """

    _OUR_FILE: str = os.path.normcase(os.path.abspath(__file__))

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        extra: dict[str, Any] = kwargs.get("extra", {})
        ctx = _log_ctx.get() or {}
        extra.update(ctx)

        # 构建显示字符串（格式：key=value key=value）
        # 先放上下文字段（req_id/user_id/client_ip），再放其余结构化字段
        parts: list[str] = []
        for key in ("req_id", "user_id", "client_ip"):
            if key in extra:
                parts.append(f"{key}={extra[key]}")

        # 折叠其余结构化字段（method/path/body/status/cost_ms/error_type 等）
        for key, value in extra.items():
            if key in (
                "req_id",
                "user_id",
                "client_ip",
                "extra_fields",
                "event_type",
            ) or key.startswith("_caller_"):
                continue
            if value is not None and value != "":
                parts.append(f"{key}={value}")

        extra["extra_fields"] = " ".join(parts) if parts else "-"

        kwargs["extra"] = extra
        return msg, kwargs

    def log(self, level: int, msg: Any, *args: Any, **kwargs: Any) -> None:
        """覆写 log()：在调用底层 logger 前自动注入真实 caller 信息。

        标准 LoggerAdapter.log() 不处理 stacklevel，导致 caller 信息错误。
        本方法从调用栈中提取第一个位于本模块和 stdlib logging 之外的帧，
        将其 module/func/lineno 注入 extra。
        """
        if not self.isEnabledFor(level):
            return
        msg, kwargs = self.process(msg, kwargs)
        # 注入真实 caller（若调用方未显式提供 _caller_*）
        extra = kwargs.get("extra", {})
        if "_caller_module" not in extra:
            self._inject_caller_info(extra)
            kwargs["extra"] = extra
        self.logger.log(level, msg, *args, **kwargs)

    @classmethod
    def _inject_caller_info(cls, extra: dict[str, Any]) -> None:
        """从调用栈中提取第一个非本模块、非 stdlib logging 的帧。

        结果写入 extra 的 _caller_module / _caller_func / _caller_lineno 键。
        """
        try:
            f: Any = inspect.currentframe()
            # 跳过 _inject_caller_info → ContextAdapter.log → LoggerAdapter.{debug,info,...}（stdlib）
            f = f.f_back if f else None  # _inject_caller_info
            while f:
                filename = os.path.normcase(f.f_code.co_filename)
                if filename == cls._OUR_FILE or _is_stdlib_logging(filename):
                    f = f.f_back
                    continue
                extra["_caller_module"] = os.path.splitext(os.path.basename(filename))[0]
                extra["_caller_func"] = f.f_code.co_name
                extra["_caller_lineno"] = f.f_lineno
                return
        except Exception:
            pass  # 静默降级：不会崩溃，只是 caller 信息回退到默认值


# ---------------------------------------------------------------------------
# 全局 logger 实例（模块导入即用）
# ---------------------------------------------------------------------------

logger = ContextAdapter(logging.getLogger("ragnexus"), {})


# ---------------------------------------------------------------------------
# 自定义 Formatter — 控制台截断
# ---------------------------------------------------------------------------


class _TruncatingColoredFormatter(ColoredFormatter):
    """ColoredFormatter 子类，截断最终格式化行（含 extra 字段），不改变原始 record。"""

    def __init__(self, *args: Any, max_length: int = 500, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.max_length = max_length

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        if len(formatted) > self.max_length:
            formatted = formatted[: self.max_length] + "...\n"
        return formatted


# ---------------------------------------------------------------------------
# 调用栈辅助 — _is_stdlib_logging & CallerFilter
# ---------------------------------------------------------------------------


def _is_stdlib_logging(filename: str) -> bool:
    """判断文件名是否属于 Python 标准库 logging 模块。"""
    return "logging" in filename.replace("\\", "/")


class CallerFilter(logging.Filter):
    """LogRecord Filter：将 extra 中的 _caller_* 字段映射为 record 属性。

    若 _caller_* 未设置（直接调用方），回退到 LogRecord 自身的 module/funcName/lineno。
    格式化模板引用 ``%(caller_module)s`` / ``%(caller_func)s`` / ``%(caller_lineno)d``。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.caller_module = getattr(record, "_caller_module", None) or record.module
        record.caller_func = getattr(record, "_caller_func", None) or record.funcName
        record.caller_lineno = getattr(record, "_caller_lineno", None) or record.lineno
        # 给 formatter 引用的占位符提供默认值，避免第三方/裸日志 KeyError
        record.event_type = getattr(record, "event_type", None) or "-"
        record.extra_fields = getattr(record, "extra_fields", None) or "-"
        return True


# ---------------------------------------------------------------------------
# 内部辅助 — 表名提取 & 旧日志清理
# ---------------------------------------------------------------------------

_TABLE_RE = re.compile(r"(?:FROM|JOIN|INTO|UPDATE)\s+([\"\w.]+)", re.IGNORECASE)


def _extract_table(query: str) -> str:
    """从 SQL 查询中启发式提取表名。"""
    match = _TABLE_RE.search(query)
    if match:
        return match.group(1).strip('"')
    return "?"


def _is_integrity_error(exc: Exception) -> bool:
    """判断异常是否为数据库完整性约束冲突（而非基础设施故障）。"""
    try:
        import asyncpg

        return isinstance(exc, asyncpg.IntegrityConstraintViolationError)
    except ImportError:
        return False


def _cleanup_old_logs(log_dir: Path, retention_days: int = 30) -> None:
    """删除超过 retention_days 天的日志目录。"""
    if not log_dir.exists():
        return
    cutoff = datetime.now() - timedelta(days=retention_days)
    for entry in log_dir.iterdir():
        if not entry.is_dir():
            continue
        try:
            dir_date = datetime.strptime(entry.name, "%Y-%m-%d")
            if dir_date < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except ValueError:
            continue


# ---------------------------------------------------------------------------
# setup_logging — 一键配置
# ---------------------------------------------------------------------------


def setup_logging(cfg: Settings) -> logging.handlers.QueueListener:
    """配置日志系统，返回 QueueListener（调用方在应用关闭时调用 ``.stop()``）。

    配置内容：
    - 按日创建 ``logs/YYYY-MM-DD/`` 目录
    - 控制台 Handler（colorlog 彩色，500 字截断，全级别）
    - 文件 Handler（``app.log``，全级别，10 MB 滚动，不截断）
    - 错误文件 Handler（``error.log``，仅 ERROR+，10 MB 滚动）
    - QueueHandler + QueueListener 后台异步写入
    - 超过 30 天的旧日志目录自动清理
    """
    log_dir = Path(cfg.LOG_DIR)
    today_str = datetime.now().strftime("%Y-%m-%d")
    date_dir = log_dir / today_str
    date_dir.mkdir(parents=True, exist_ok=True)

    _cleanup_old_logs(log_dir, retention_days=30)

    # --- 队列（满则丢弃当前新记录（最旧优先保留），不阻塞）---
    log_queue: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=cfg.LOG_QUEUE_SIZE)

    # --- 控制台 Handler（colorlog 彩色）---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO))
    console_formatter = _TruncatingColoredFormatter(
        "%(asctime)s | %(log_color)s%(levelname)-8s%(reset)s | "
        "%(caller_module)s:%(caller_func)s:%(caller_lineno)d | "
        "%(event_type)s | %(extra_fields)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        max_length=cfg.LOG_CONSOLE_MAX_LENGTH,
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
    )
    console_handler.setFormatter(console_formatter)

    # --- 文件 Handler（app.log，全级别，10 MB 滚动）---
    app_handler = logging.handlers.RotatingFileHandler(
        date_dir / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=100,
        encoding="utf-8",
    )
    app_handler.setLevel(logging.DEBUG)
    app_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | "
        "%(caller_module)s:%(caller_func)s:%(caller_lineno)d | "
        "%(event_type)s | %(extra_fields)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    app_handler.setFormatter(app_formatter)

    # --- 错误文件 Handler（error.log，仅 ERROR+）---
    error_handler = logging.handlers.RotatingFileHandler(
        date_dir / "error.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=100,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(app_formatter)

    # --- QueueHandler + QueueListener ---
    queue_handler = logging.handlers.QueueHandler(log_queue)
    listener = logging.handlers.QueueListener(
        log_queue,
        console_handler,
        app_handler,
        error_handler,
        respect_handler_level=True,
    )
    listener.start()

    # --- 配置 ragnexus logger ---
    root_logger = logging.getLogger("ragnexus")
    root_logger.setLevel(logging.DEBUG)  # 允许 DEBUG，由各 handler 级别过滤
    root_logger.handlers.clear()
    root_logger.addHandler(queue_handler)
    root_logger.propagate = False
    root_logger.addFilter(CallerFilter())

    return listener


# ---------------------------------------------------------------------------
# @log_model_call — 模型调用装饰器
# ---------------------------------------------------------------------------


def log_model_call(model: str, prompt_arg: int = 0):
    """包装 async 函数，自动记录 MODEL_REQUEST / MODEL_RESPONSE 事件。

    用法::

        @log_model_call("gpt-4")
        async def call_llm(prompt: str) -> str:
            ...

    对于 bound method，传入 prompt_arg=1 跳过 self::

        @log_model_call("text-embedding-v3", prompt_arg=1)
        async def embed(self, texts: list[str]) -> list[list[float]]:
            ...

    当 ``LOG_MODEL_CONTENT=True`` 时记录截断的 prompt/response 文本；
    当 ``LOG_MODEL_CONTENT=False`` 时仅记录长度等元数据。
    """

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            cfg = get_settings()
            log_content: bool = cfg.LOG_MODEL_CONTENT

            # --- MODEL_REQUEST ---
            extra_request: dict[str, Any] = {
                "event_type": "MODEL_REQUEST",
                "model": model,
            }
            prompt_val: str | None = None
            if len(args) > prompt_arg:
                prompt_val = str(args[prompt_arg])
            elif "prompt" in kwargs:
                prompt_val = str(kwargs["prompt"])
            if prompt_val is not None:
                if log_content:
                    extra_request["prompt"] = prompt_val
                else:
                    extra_request["prompt_length"] = len(prompt_val)
            logger.info("模型调用开始", extra=extra_request)

            try:
                result = await func(*args, **kwargs)
                elapsed_ms = (time.monotonic() - start) * 1000

                # --- MODEL_RESPONSE（成功）---
                extra_response: dict[str, Any] = {
                    "event_type": "MODEL_RESPONSE",
                    "model": model,
                    "cost_ms": round(elapsed_ms, 2),
                }
                if result is not None:
                    if log_content:
                        extra_response["response"] = str(result)
                    else:
                        extra_response["response_length"] = len(str(result))
                logger.info("模型调用完成", extra=extra_response)
                return result

            except Exception as exc:
                elapsed_ms = (time.monotonic() - start) * 1000

                # --- MODEL_RESPONSE（失败）---
                extra_error: dict[str, Any] = {
                    "event_type": "MODEL_RESPONSE",
                    "model": model,
                    "cost_ms": round(elapsed_ms, 2),
                    "error": str(exc),
                }
                logger.info("模型调用失败", extra=extra_error)
                raise

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# LoggedPool — asyncpg.Pool 查询代理
# ---------------------------------------------------------------------------


class LoggedPool:
    """包装 asyncpg.Pool，对 fetch / fetchrow / fetchval / execute 自动记录 DB_QUERY。

    DEBUG 级别记录，字段：op / table / cost_ms / rows。
    异常时以 ERROR 级别记录。
    rows 仅对 fetch（返回 list）做计数，其余操作设为 0。
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def fetch(self, query: str, *args: Any, **kwargs: Any) -> Any:
        return await self._log("fetch", query, self._pool.fetch, *args, **kwargs)

    async def fetchrow(self, query: str, *args: Any, **kwargs: Any) -> Any:
        return await self._log("fetchrow", query, self._pool.fetchrow, *args, **kwargs)

    async def fetchval(self, query: str, *args: Any, **kwargs: Any) -> Any:
        return await self._log("fetchval", query, self._pool.fetchval, *args, **kwargs)

    async def execute(self, query: str, *args: Any, **kwargs: Any) -> Any:
        return await self._log("execute", query, self._pool.execute, *args, **kwargs)

    def acquire(self) -> Any:
        """透传 acquire()，返回底层 pool 的 async context manager。"""
        return self._pool.acquire()

    async def _log(self, op: str, query: str, method: Any, *args: Any, **kwargs: Any) -> Any:
        start = time.monotonic()
        try:
            result = await method(query, *args, **kwargs)
            elapsed_ms = (time.monotonic() - start) * 1000
            rows = len(result) if isinstance(result, list) else 0
            logger.debug(
                "DB查询完成",
                extra={
                    "event_type": "DB_QUERY",
                    "op": op,
                    "table": _extract_table(query),
                    "cost_ms": round(elapsed_ms, 2),
                    "rows": rows,
                },
            )
            return result
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            # 约束冲突和基础设施故障统一为 ERROR，通过消息和 error_type 区分
            _is_integrity = _is_integrity_error(exc)
            logger.error(
                "DB约束冲突" if _is_integrity else "DB查询失败",
                extra={
                    "event_type": "DB_QUERY",
                    "op": op,
                    "table": _extract_table(query),
                    "cost_ms": round(elapsed_ms, 2),
                    "error_type": exc.__class__.__name__,
                    "error_message": str(exc),
                },
            )
            raise
