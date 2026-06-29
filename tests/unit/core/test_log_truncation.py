"""验证日志文件不截断：>200 字符的内容在文件输出中完整保留。

测试覆盖：
1. log_model_call 长 prompt（>200 字符）→ 文件日志完整
2. log_model_call 长 response（>200 字符）→ 文件日志完整
3. 文件 Handler 使用标准 Formatter，不做字段截断
"""

import logging

import pytest

from ragnexus.core.logger import log_model_call


class FakeSettings:
    """模拟 Settings，提供日志所需的最小配置。"""

    LOG_LEVEL: str = "DEBUG"
    LOG_DIR: str = "logs"
    LOG_QUEUE_SIZE: int = 100
    LOG_CONSOLE_MAX_LENGTH: int = 500
    LOG_MODEL_CONTENT: bool = True


@pytest.fixture
def fake_settings(monkeypatch):
    """注入假配置。"""
    import ragnexus.core.logger as mod

    monkeypatch.setattr(mod, "get_settings", lambda: FakeSettings())


def _flush_and_stop(listener) -> None:
    """安全刷新队列并停止 listener。"""
    if listener._thread is not None:
        listener._thread.join(timeout=2)
    listener.stop()


def _read_app_log(tmp_path) -> str:
    """读取生成的 app.log 内容。"""
    log_files = list(tmp_path.rglob("app.log"))
    assert log_files, "应生成 app.log 文件"
    return log_files[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_log_model_call_no_truncation_on_long_prompt(
    tmp_path, monkeypatch, fake_settings
):
    """≥200 字符的 prompt 在文件日志中完整输出。"""
    import ragnexus.core.logger as mod

    monkeypatch.setattr(FakeSettings, "LOG_DIR", str(tmp_path))

    listener = mod.setup_logging(FakeSettings())
    try:

        @log_model_call("test-model")
        async def fake_llm(prompt: str) -> str:
            return "short response"

        long_prompt = "A" * 250  # >200 字符
        await fake_llm(long_prompt)

        _flush_and_stop(listener)
        log_content = _read_app_log(tmp_path)

        assert (
            long_prompt in log_content
        ), f"文件日志应包含完整 prompt（{len(long_prompt)} 字符），不应截断"
        assert "..." not in log_content, "截断标记不应出现"
    finally:
        try:
            listener.stop()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_log_model_call_no_truncation_on_long_response(
    tmp_path, monkeypatch, fake_settings
):
    """≥200 字符的 response 在文件日志中完整输出。"""
    import ragnexus.core.logger as mod

    monkeypatch.setattr(FakeSettings, "LOG_DIR", str(tmp_path))

    listener = mod.setup_logging(FakeSettings())
    try:

        @log_model_call("test-model")
        async def fake_llm(prompt: str) -> str:
            return "B" * 300  # >200 字符

        await fake_llm("short prompt")

        _flush_and_stop(listener)
        log_content = _read_app_log(tmp_path)

        assert (
            "B" * 300 in log_content
        ), "文件日志应包含完整 response（300 字符），不应截断"
        assert "..." not in log_content, "截断标记不应出现"
    finally:
        try:
            listener.stop()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_file_handler_plain_formatter_no_truncation(tmp_path, monkeypatch):
    """文件 Handler 使用标准 logging.Formatter，>500 字符消息完整保留。"""
    import ragnexus.core.logger as mod

    monkeypatch.setattr(FakeSettings, "LOG_DIR", str(tmp_path))

    listener = mod.setup_logging(FakeSettings())
    try:
        test_logger = logging.getLogger("ragnexus")
        long_message = "C" * 600

        record = test_logger.makeRecord(
            "ragnexus",
            logging.INFO,
            "fn",
            1,
            long_message,
            (),
            None,
            extra={
                "event_type": "TEST_EVENT",
                "extra_fields": "",
            },
        )
        test_logger.handle(record)

        _flush_and_stop(listener)
        log_content = _read_app_log(tmp_path)

        assert (
            long_message in log_content
        ), f"文件日志应包含完整消息（{len(long_message)} 字符），不应截断"
        assert "..." not in log_content, "截断标记不应出现"
    finally:
        try:
            listener.stop()
        except Exception:
            pass
