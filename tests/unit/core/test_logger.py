"""RAGNexus 日志系统核心 TDD 测试

测试覆盖：
1. 配置项默认值（LOG_DIR / LOG_QUEUE_SIZE / LOG_CONSOLE_MAX_LENGTH / LOG_MODEL_CONTENT）
2. ContextAdapter 自动注入 ContextVar 字段
3. set_log_context / clear_log_context
4. @log_model_call 装饰器（MODEL_REQUEST / MODEL_RESPONSE）
5. LoggedPool 代理（DB_QUERY）
6. setup_logging handler 配置
"""

# pyright: reportAttributeAccessIssue=false
import logging
import logging.handlers
import tempfile
import time
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from ragnexus.config import Settings
from ragnexus.core.logger import (
    CallerFilter,
    ContextAdapter,
    LoggedPool,
    _log_ctx,
    clear_log_context,
    log_model_call,
    set_log_context,
    setup_logging,
)

# ============================================================================
# 辅助工具
# ============================================================================


class _ListHandler(logging.Handler):
    """捕获日志记录到列表的 Handler。"""

    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__()
        self._records = records

    def emit(self, record: logging.LogRecord) -> None:
        self._records.append(record)


def _get_rag_logger() -> logging.Logger:
    return logging.getLogger("ragnexus")


def _add_capture_handler(records: list[logging.LogRecord]) -> _ListHandler:
    handler = _ListHandler(records)
    handler.setLevel(logging.DEBUG)
    rag = _get_rag_logger()
    rag.addHandler(handler)
    rag.setLevel(logging.DEBUG)
    return handler


def _remove_capture_handler(handler: _ListHandler) -> None:
    _get_rag_logger().removeHandler(handler)


# ============================================================================
# TestConfigDefaults
# ============================================================================


class TestConfigDefaults:
    """配置项默认值测试"""

    def test_log_dir_default(self) -> None:
        s = Settings()
        assert s.LOG_DIR == "logs"

    def test_log_queue_size_default(self) -> None:
        s = Settings()
        assert s.LOG_QUEUE_SIZE == 5000

    def test_log_console_max_length_default(self) -> None:
        s = Settings()
        assert s.LOG_CONSOLE_MAX_LENGTH == 500

    def test_log_model_content_default(self) -> None:
        s = Settings()
        assert s.LOG_MODEL_CONTENT is True


# ============================================================================
# TestContextVar
# ============================================================================


class TestContextVar:
    """ContextVar 上下文注入测试"""

    def test_set_log_context_updates_var(self) -> None:
        set_log_context(req_id="abc123", user_id="user1")
        assert _log_ctx.get() == {"req_id": "abc123", "user_id": "user1"}

    def test_clear_log_context_resets_to_empty(self) -> None:
        set_log_context(req_id="abc123")
        clear_log_context()
        assert _log_ctx.get() == {}

    def test_default_context_is_empty(self) -> None:
        clear_log_context()
        assert _log_ctx.get() == {}


# ============================================================================
# TestContextAdapter
# ============================================================================


class TestContextAdapter:
    """ContextAdapter 测试"""

    def test_injects_context_vars_into_extra(self) -> None:
        set_log_context(req_id="abc123", user_id="user1")
        adapter = ContextAdapter(logging.getLogger("test_adapter"), {})

        msg, kwargs = adapter.process(
            "test msg", {"extra": {"event_type": "API_REQUEST"}}
        )

        assert kwargs["extra"]["req_id"] == "abc123"
        assert kwargs["extra"]["user_id"] == "user1"
        assert kwargs["extra"]["event_type"] == "API_REQUEST"

        clear_log_context()

    def test_extra_fields_string_includes_context_values(self) -> None:
        set_log_context(req_id="abc123", client_ip="127.0.0.1")
        adapter = ContextAdapter(logging.getLogger("test_adapter"), {})

        _msg, kwargs = adapter.process("test", {"extra": {"event_type": "API_REQUEST"}})

        extra_fields: str = kwargs["extra"]["extra_fields"]
        assert "req_id=abc123" in extra_fields
        assert "client_ip=127.0.0.1" in extra_fields

        clear_log_context()

    def test_extra_fields_is_dash_when_no_context(self) -> None:
        clear_log_context()
        adapter = ContextAdapter(logging.getLogger("test_adapter"), {})

        _msg, kwargs = adapter.process("test", {"extra": {"event_type": "API_REQUEST"}})

        assert kwargs["extra"]["extra_fields"] == "-"


# ============================================================================
# TestLogModelCall
# ============================================================================


class TestLogModelCall:
    """@log_model_call 装饰器测试"""

    @pytest.fixture(autouse=True)
    def _setup(self) -> Generator[None, None, None]:
        self.records: list[logging.LogRecord] = []
        self._handler = _add_capture_handler(self.records)
        yield
        _remove_capture_handler(self._handler)

    def _by_event(self, event_type: str) -> list[logging.LogRecord]:
        return [r for r in self.records if getattr(r, "event_type", None) == event_type]

    async def test_logs_request_and_response_on_success(self) -> None:
        @log_model_call("test-model-v1")
        async def mock_llm(prompt: str) -> str:
            return f"response to: {prompt}"

        result = await mock_llm("hello world")
        assert result == "response to: hello world"

        requests = self._by_event("MODEL_REQUEST")
        responses = self._by_event("MODEL_RESPONSE")

        assert len(requests) == 1, f"应有 1 条 MODEL_REQUEST，实际: {len(requests)}"
        assert len(responses) == 1, f"应有 1 条 MODEL_RESPONSE，实际: {len(responses)}"

        assert requests[0].model == "test-model-v1"
        assert "hello world" in requests[0].prompt

        assert responses[0].model == "test-model-v1"
        assert responses[0].cost_ms >= 0
        assert "response to:" in responses[0].response

    async def test_logs_model_response_with_error_on_failure(self) -> None:
        @log_model_call("failing-model")
        async def mock_llm(prompt: str) -> str:
            raise ValueError("模拟模型错误")

        with pytest.raises(ValueError, match="模拟模型错误"):
            await mock_llm("test")

        responses = self._by_event("MODEL_RESPONSE")
        assert len(responses) == 1
        assert responses[0].error == "模拟模型错误"
        assert responses[0].cost_ms >= 0
        assert responses[0].model == "failing-model"

    async def test_handles_kwargs_prompt(self) -> None:
        """当 prompt 通过 kwargs 传递时也能正确捕获"""

        @log_model_call("kwargs-model")
        async def mock_llm(**kwargs: str) -> str:
            return f"got: {kwargs['prompt']}"

        await mock_llm(prompt="keyword prompt")

        requests = self._by_event("MODEL_REQUEST")
        assert len(requests) == 1
        assert "keyword prompt" in requests[0].prompt

    async def test_log_model_content_false_omits_prompt_response(self) -> None:
        """LOG_MODEL_CONTENT=False 时：记录 prompt_length/response_length 而不记录内容。"""
        mock_cfg = Settings(LOG_MODEL_CONTENT=False)

        @log_model_call("no-content-model")
        async def mock_llm(prompt: str) -> str:
            return "short response"

        with patch("ragnexus.core.logger.get_settings", return_value=mock_cfg):
            await mock_llm("hello world")

        requests = self._by_event("MODEL_REQUEST")
        responses = self._by_event("MODEL_RESPONSE")

        assert len(requests) == 1
        assert not hasattr(requests[0], "prompt"), "不应包含 prompt 内容"
        assert requests[0].prompt_length == 11  # len("hello world")

        assert len(responses) == 1
        assert not hasattr(responses[0], "response"), "不应包含 response 内容"
        assert responses[0].response_length == 14  # len("short response")

    async def test_log_model_content_true_includes_content(self) -> None:
        """LOG_MODEL_CONTENT=True（默认）时：保留原有行为，记录截断内容。"""
        mock_cfg = Settings(LOG_MODEL_CONTENT=True)

        @log_model_call("content-model")
        async def mock_llm(prompt: str) -> str:
            return "response text"

        with patch("ragnexus.core.logger.get_settings", return_value=mock_cfg):
            await mock_llm("prompt text")

        requests = self._by_event("MODEL_REQUEST")
        responses = self._by_event("MODEL_RESPONSE")

        assert len(requests) == 1
        assert "prompt text" in requests[0].prompt

        assert len(responses) == 1
        assert "response text" in responses[0].response


# ============================================================================
# TestLoggedPool
# ============================================================================


class TestLoggedPool:
    """LoggedPool 代理测试"""

    @pytest.fixture(autouse=True)
    def _setup(self) -> Generator[None, None, None]:
        self.records: list[logging.LogRecord] = []
        self._handler = _add_capture_handler(self.records)
        yield
        _remove_capture_handler(self._handler)

    def _db_records(self) -> list[logging.LogRecord]:
        return [r for r in self.records if getattr(r, "event_type", None) == "DB_QUERY"]

    async def test_fetch_logs_db_query(self) -> None:
        mock_pool = AsyncMock()
        mock_pool.fetch.return_value = [{"id": 1}, {"id": 2}]

        logged = LoggedPool(mock_pool)
        result = await logged.fetch("SELECT * FROM users WHERE active = $1", True)

        assert len(result) == 2
        mock_pool.fetch.assert_called_once_with(
            "SELECT * FROM users WHERE active = $1", True
        )

        db_records = self._db_records()
        assert len(db_records) == 1
        assert db_records[0].op == "fetch"
        assert db_records[0].table == "users"
        assert db_records[0].rows == 2
        assert db_records[0].cost_ms >= 0

    async def test_fetchrow_logs_db_query(self) -> None:
        mock_pool = AsyncMock()
        mock_pool.fetchrow.return_value = {"id": 1}

        logged = LoggedPool(mock_pool)
        result = await logged.fetchrow("SELECT * FROM users WHERE id = $1", 1)

        assert result == {"id": 1}

        db_records = self._db_records()
        assert len(db_records) == 1
        assert db_records[0].op == "fetchrow"
        assert db_records[0].table == "users"
        # fetchrow 返回单 Record（非 list），rows 固定为 0
        assert db_records[0].rows == 0

    async def test_fetchval_logs_db_query(self) -> None:
        mock_pool = AsyncMock()
        mock_pool.fetchval.return_value = 42

        logged = LoggedPool(mock_pool)
        result = await logged.fetchval("SELECT count(*) FROM users")

        assert result == 42

        db_records = self._db_records()
        assert len(db_records) == 1
        assert db_records[0].op == "fetchval"

    async def test_execute_logs_db_query(self) -> None:
        mock_pool = AsyncMock()
        mock_pool.execute.return_value = "OK"

        logged = LoggedPool(mock_pool)
        result = await logged.execute("UPDATE users SET active = $1", False)

        assert result == "OK"

        db_records = self._db_records()
        assert len(db_records) == 1
        assert db_records[0].op == "execute"
        assert db_records[0].table == "users"

    async def test_query_failure_logs_error(self) -> None:
        mock_pool = AsyncMock()
        mock_pool.fetch.side_effect = RuntimeError("连接超时")

        logged = LoggedPool(mock_pool)

        with pytest.raises(RuntimeError, match="连接超时"):
            await logged.fetch("SELECT * FROM users")

        error_records = [r for r in self.records if r.levelno == logging.ERROR]
        assert len(error_records) == 1
        assert error_records[0].event_type == "DB_QUERY"

    async def test_acquire_passthrough(self) -> None:
        """acquire() 透传到底层 pool，返回原始 async context manager。"""
        mock_pool = Mock(name="raw_pool")
        mock_conn = Mock(name="conn")
        mock_pool.acquire.return_value = mock_conn

        logged = LoggedPool(mock_pool)
        result = logged.acquire()

        mock_pool.acquire.assert_called_once()
        assert result is mock_conn, "应透传底层 pool.acquire() 的返回值"


# ============================================================================
# TestSetupLogging
# ============================================================================


class TestSetupLogging:
    """setup_logging 配置测试"""

    def test_creates_log_directory_and_files(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            cfg = Settings(LOG_DIR=tmpdir, LOG_LEVEL="DEBUG")
            listener = setup_logging(cfg)

            try:
                rag_logger = _get_rag_logger()

                # QueueHandler 应已配置
                queue_handlers = [
                    h
                    for h in rag_logger.handlers
                    if isinstance(h, logging.handlers.QueueHandler)
                ]
                assert len(queue_handlers) == 1, "应配置 1 个 QueueHandler"

                # 写一条日志
                rag_logger.info("setup test message", extra={"event_type": "BIZ_EVENT"})

                # 等待后台 QueueListener 写出
                time.sleep(0.5)

                # 检查日志文件已创建
                log_files = list(Path(tmpdir).rglob("*.log"))
                assert (
                    len(log_files) >= 2
                ), f"应有 app.log 和 error.log，实际文件: {log_files}"

            finally:
                listener.stop()

    def test_propagate_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            cfg = Settings(LOG_DIR=tmpdir)
            listener = setup_logging(cfg)

            try:
                rag_logger = _get_rag_logger()
                assert (
                    rag_logger.propagate is False
                ), "ragnexus logger 不应传播到根 logger"
            finally:
                listener.stop()

    def test_clears_existing_handlers(self) -> None:
        """重复调用 setup_logging 应先清理旧 handler。"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            cfg = Settings(LOG_DIR=tmpdir)

            listener1 = setup_logging(cfg)
            handler_count_1 = len(_get_rag_logger().handlers)
            listener1.stop()

            listener2 = setup_logging(cfg)
            handler_count_2 = len(_get_rag_logger().handlers)
            listener2.stop()

            # 两次调用后 handler 数应一致（因为 clear 了旧的）
            assert (
                handler_count_1 == handler_count_2
            ), f"handler count changed: {handler_count_1} → {handler_count_2}"


class TestCallerFilter:
    """测试 CallerFilter 将 _caller_* 映射到 record 属性。"""

    @staticmethod
    def _make_record(extra_attrs: dict) -> logging.LogRecord:
        """创建一个带有自定义 extra 属性的 LogRecord。"""
        record = logging.LogRecord(
            name="ragnexus",
            level=logging.INFO,
            pathname=__file__,
            lineno=42,
            msg="test",
            args=(),
            exc_info=None,
        )
        for k, v in extra_attrs.items():
            setattr(record, k, v)
        return record

    def test_without_caller_attrs_falls_back_to_record(self) -> None:
        """未设置 _caller_* 时回退到 record 自身的 module/funcName/lineno。"""
        record = self._make_record({})
        f = CallerFilter()
        f.filter(record)
        assert record.caller_module == record.module
        assert record.caller_func == record.funcName
        assert record.caller_lineno == record.lineno

    def test_with_caller_attrs_uses_them(self) -> None:
        """设置 _caller_* 后使用 _caller_* 的值。"""
        record = self._make_record(
            {
                "_caller_module": "pgvector",
                "_caller_func": "upsert",
                "_caller_lineno": 123,
            }
        )
        f = CallerFilter()
        f.filter(record)
        assert record.caller_module == "pgvector"
        assert record.caller_func == "upsert"
        assert record.caller_lineno == 123

    def test_partial_caller_attrs(self) -> None:
        """部分 _caller_* 为空时各自回退。"""
        record = self._make_record(
            {"_caller_module": "middleware", "_caller_func": "", "_caller_lineno": 0}
        )
        f = CallerFilter()
        f.filter(record)
        assert record.caller_module == "middleware"
        # 空字符串 → False → 回退到 record.funcName
        assert record.caller_func == record.funcName
        # 0 → False → 回退到 record.lineno
        assert record.caller_lineno == record.lineno
