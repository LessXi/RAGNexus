"""Langfuse 可观测客户端单元测试。

测试场景：
- disabled 时所有方法静默返回 None
- enabled 时 create_trace 调用 Langfuse.trace()
- enabled 时 create_span 在 trace 下创建子 span
- update_span / end_trace 正确代理
- Langfuse 异常 → try/catch 返回 None 并 log warning
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from ragnexus.observability.langfuse_client import (
    RetrieveObservability,
    get_langfuse_client,
)

# ============================================================================
# Factory 测试
# ============================================================================


class TestGetLangfuseClient:
    """测试 get_langfuse_client 工厂函数。"""

    def test_disabled_returns_noop_client(self, monkeypatch):
        """LANGFUSE_ENABLED=False 时返回 disabled 客户端。"""
        from ragnexus.config import Settings

        s = Settings(
            _env_file=None,  # type: ignore[call-arg]
            LANGFUSE_ENABLED=False,
        )
        client = get_langfuse_client(s)
        assert client._enabled is False
        assert client._client is None

    def test_enabled_creates_langfuse_client(self, monkeypatch):
        """LANGFUSE_ENABLED=True 时创建 Langfuse 客户端。"""
        from ragnexus.config import Settings

        s = Settings(
            _env_file=None,  # type: ignore[call-arg]
            LANGFUSE_ENABLED=True,
            LANGFUSE_HOST="http://localhost:3000",
            LANGFUSE_PUBLIC_KEY="pk-test",
            LANGFUSE_SECRET_KEY="sk-test",
        )
        with patch("ragnexus.observability.langfuse_client.Langfuse") as MockLangfuse:
            mock_lf = MagicMock()
            MockLangfuse.return_value = mock_lf
            client = get_langfuse_client(s)
            assert client._enabled is True
            assert client._client is mock_lf
            MockLangfuse.assert_called_once_with(
                host="http://localhost:3000",
                public_key="pk-test",
                secret_key="sk-test",
            )


# ============================================================================
# RetrieveObservability 测试
# ============================================================================


class TestRetrieveObservabilityDisabled:
    """disabled 时所有方法静默返回 None / noop。"""

    def test_create_trace_returns_none(self):
        o = RetrieveObservability(enabled=False)
        assert o.create_trace("test-trace") is None

    def test_create_span_returns_none(self):
        o = RetrieveObservability(enabled=False)
        assert o.create_span(None, "test-span") is None  # type: ignore[arg-type]

    def test_update_span_is_noop(self):
        o = RetrieveObservability(enabled=False)
        o.update_span(None)  # type: ignore[arg-type]  # 不抛异常

    def test_end_trace_is_noop(self):
        o = RetrieveObservability(enabled=False)
        o.end_trace(None)  # type: ignore[arg-type]  # 不抛异常

    def test_create_trace_returns_none_when_client_is_none(self):
        """enabled=True 但 client=None 时也静默返回 None。"""
        o = RetrieveObservability(enabled=True, client=None)
        assert o.create_trace("test") is None


class TestRetrieveObservabilityEnabled:
    """enabled 时方法正确代理 Langfuse。"""

    def test_create_trace_calls_langfuse(self):
        """create_trace 调用 client.trace() 并返回 dict。"""
        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_trace.id = "trace-1"
        mock_client.trace.return_value = mock_trace

        o = RetrieveObservability(enabled=True, client=mock_client)
        result = o.create_trace("my-trace", metadata={"key": "val"})

        mock_client.trace.assert_called_once_with(
            name="my-trace", metadata={"key": "val"}
        )
        assert result is not None
        assert result["id"] == "trace-1"
        assert result["trace"] is mock_trace

    def test_create_trace_without_metadata(self):
        """metadata 为 None 时不传 metadata 参数。"""
        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_trace.id = "trace-2"
        mock_client.trace.return_value = mock_trace

        o = RetrieveObservability(enabled=True, client=mock_client)
        result = o.create_trace("simple-trace")

        mock_client.trace.assert_called_once_with(name="simple-trace", metadata=None)
        assert result is not None
        assert result["id"] == "trace-2"

    def test_create_span_calls_trace_span(self):
        """create_span 调用 trace["trace"].span()。"""
        mock_client = MagicMock()
        mock_trace_obj = MagicMock()
        mock_span = MagicMock()
        mock_span.id = "span-1"
        mock_trace_obj.span.return_value = mock_span

        trace_dict = {"id": "trace-1", "trace": mock_trace_obj}
        o = RetrieveObservability(enabled=True, client=mock_client)
        result = o.create_span(trace_dict, "embedding", input_data={"q": "hello"})

        mock_trace_obj.span.assert_called_once_with(
            name="embedding", input={"q": "hello"}
        )
        assert result is not None
        assert result["id"] == "span-1"
        assert result["span"] is mock_span

    def test_create_span_without_input(self):
        """input_data 为 None 时不传 input。"""
        mock_client = MagicMock()
        mock_trace_obj = MagicMock()
        mock_span = MagicMock()
        mock_trace_obj.span.return_value = mock_span

        trace_dict = {"id": "trace-1", "trace": mock_trace_obj}
        o = RetrieveObservability(enabled=True, client=mock_client)
        o.create_span(trace_dict, "no-input-span")

        mock_trace_obj.span.assert_called_once_with(name="no-input-span", input=None)

    def test_update_span_calls_span_update(self):
        """update_span 调用 span["span"].update(output=...)."""
        mock_client = MagicMock()
        mock_span_obj = MagicMock()
        span_dict = {"id": "span-1", "span": mock_span_obj}

        o = RetrieveObservability(enabled=True, client=mock_client)
        o.update_span(span_dict, output_data={"score": 0.95})

        mock_span_obj.update.assert_called_once_with(output={"score": 0.95})

    def test_update_span_without_output(self):
        """output_data 为 None 时也调用 update。"""
        mock_client = MagicMock()
        mock_span_obj = MagicMock()
        span_dict = {"id": "span-1", "span": mock_span_obj}

        o = RetrieveObservability(enabled=True, client=mock_client)
        o.update_span(span_dict)

        mock_span_obj.update.assert_called_once_with(output=None)

    def test_end_trace_calls_trace_update(self):
        """end_trace 调用 trace["trace"].update()。"""
        mock_client = MagicMock()
        mock_trace_obj = MagicMock()
        trace_dict = {"id": "trace-1", "trace": mock_trace_obj}

        o = RetrieveObservability(enabled=True, client=mock_client)
        o.end_trace(trace_dict)

        mock_trace_obj.update.assert_called_once()


# ============================================================================
# 异常处理测试
# ============================================================================


class TestRetrieveObservabilityExceptionHandling:
    """Langfuse 异常时 try/catch + log warning，不阻断业务。"""

    def test_create_trace_returns_none_on_exception(self, caplog):
        """Langfuse.trace() 抛异常 → 返回 None 并 log warning。"""
        mock_client = MagicMock()
        mock_client.trace.side_effect = RuntimeError("network error")

        o = RetrieveObservability(enabled=True, client=mock_client)
        with caplog.at_level(logging.WARNING):
            result = o.create_trace("failing-trace")

        assert result is None
        assert "Failed to create Langfuse trace" in caplog.text
        assert "network error" in caplog.text

    def test_create_span_returns_none_on_exception(self, caplog):
        """trace.span() 抛异常 → 返回 None 并 log warning。"""
        mock_client = MagicMock()
        mock_trace_obj = MagicMock()
        mock_trace_obj.span.side_effect = RuntimeError("span error")
        trace_dict = {"id": "trace-1", "trace": mock_trace_obj}

        o = RetrieveObservability(enabled=True, client=mock_client)
        with caplog.at_level(logging.WARNING):
            result = o.create_span(trace_dict, "failing-span")

        assert result is None
        assert "Failed to create Langfuse span" in caplog.text

    def test_update_span_logs_warning_on_exception(self, caplog):
        """span.update() 抛异常 → log warning，不抛异常。"""
        mock_client = MagicMock()
        mock_span_obj = MagicMock()
        mock_span_obj.update.side_effect = RuntimeError("update error")
        span_dict = {"id": "span-1", "span": mock_span_obj}

        o = RetrieveObservability(enabled=True, client=mock_client)
        with caplog.at_level(logging.WARNING):
            o.update_span(span_dict, output_data={"x": 1})

        assert "Failed to update Langfuse span" in caplog.text

    def test_end_trace_logs_warning_on_exception(self, caplog):
        """trace.update() 抛异常 → log warning，不抛异常。"""
        mock_client = MagicMock()
        mock_trace_obj = MagicMock()
        mock_trace_obj.update.side_effect = RuntimeError("end error")
        trace_dict = {"id": "trace-1", "trace": mock_trace_obj}

        o = RetrieveObservability(enabled=True, client=mock_client)
        with caplog.at_level(logging.WARNING):
            o.end_trace(trace_dict)

        assert "Failed to end Langfuse trace" in caplog.text
