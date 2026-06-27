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
import logging
import logging.handlers
import queue
import re
import shutil
import time
from collections.abc import MutableMapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from colorlog import ColoredFormatter

from ragnexus.config import Settings

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

    同时构建 ``extra_fields`` 字符串供格式化模板引用。
    """

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        extra: dict[str, Any] = kwargs.get("extra", {})
        ctx = _log_ctx.get() or {}
        extra.update(ctx)

        # 构建条件字段显示字符串（格式：key=value key=value）
        parts: list[str] = []
        for key in ("req_id", "user_id", "client_ip"):
            if key in extra:
                parts.append(f"{key}={extra[key]}")
        extra["extra_fields"] = " ".join(parts) if parts else "-"

        kwargs["extra"] = extra
        return msg, kwargs


# ---------------------------------------------------------------------------
# 全局 logger 实例（模块导入即用）
# ---------------------------------------------------------------------------

logger = ContextAdapter(logging.getLogger("ragnexus"), {})


# ---------------------------------------------------------------------------
# 自定义 Formatter — 控制台截断
# ---------------------------------------------------------------------------


class _TruncatingColoredFormatter(ColoredFormatter):
    """ColoredFormatter 子类，超出 max_length 的消息截断，不改变原始 record。"""

    def __init__(self, *args: Any, max_length: int = 500, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.max_length = max_length

    def format(self, record: logging.LogRecord) -> str:
        orig_msg = record.msg
        orig_args = record.args
        try:
            msg_text = str(orig_msg)
            if len(msg_text) > self.max_length:
                record.msg = msg_text[: self.max_length] + "..."
                record.args = None
            return super().format(record)
        finally:
            record.msg = orig_msg
            record.args = orig_args


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

    # --- 队列（满则丢旧不阻塞）---
    log_queue: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=cfg.LOG_QUEUE_SIZE)

    # --- 控制台 Handler（colorlog 彩色）---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO))
    console_formatter = _TruncatingColoredFormatter(
        "%(asctime)s | %(log_color)s%(levelname)-8s%(reset)s | "
        "%(module)s:%(funcName)s:%(lineno)d | "
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
        "%(module)s:%(funcName)s:%(lineno)d | "
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

    return listener


# ---------------------------------------------------------------------------
# @log_model_call — 模型调用装饰器
# ---------------------------------------------------------------------------


def log_model_call(model: str):
    """包装 async 函数，自动记录 MODEL_REQUEST / MODEL_RESPONSE 事件。

    用法::

        @log_model_call("gpt-4")
        async def call_llm(prompt: str) -> str:
            ...

    记录字段：model / cost_ms / prompt（截断）/ response（截断）/ error（失败时）。
    """

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()

            # --- MODEL_REQUEST ---
            extra_request: dict[str, Any] = {
                "event_type": "MODEL_REQUEST",
                "model": model,
            }
            prompt_val: str | None = None
            if args:
                prompt_val = str(args[0])
            elif "prompt" in kwargs:
                prompt_val = str(kwargs["prompt"])
            if prompt_val is not None:
                extra_request["prompt"] = (
                    prompt_val[:200] + "..." if len(prompt_val) > 200 else prompt_val
                )
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
                    result_str = str(result)
                    extra_response["response"] = (
                        result_str[:200] + "..." if len(result_str) > 200 else result_str
                    )
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

    async def _log(self, op: str, query: str, method: Any, *args: Any, **kwargs: Any) -> Any:
        start = time.monotonic()
        try:
            result = await method(query, *args, **kwargs)
            elapsed_ms = (time.monotonic() - start) * 1000
            rows = len(result) if hasattr(result, "__len__") else 0
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
        except Exception:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.error(
                "DB查询失败",
                extra={
                    "event_type": "DB_QUERY",
                    "op": op,
                    "table": _extract_table(query),
                    "cost_ms": round(elapsed_ms, 2),
                },
            )
            raise
