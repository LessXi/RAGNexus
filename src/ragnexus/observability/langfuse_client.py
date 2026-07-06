"""Langfuse 可观测客户端 — fire-and-forget 旁路模式。

所有方法在 LANGFUSE_ENABLED=False 时静默返回 None/不操作；
创建追踪失败时 catch 异常并 log warning，不阻断业务。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langfuse import Langfuse

if TYPE_CHECKING:
    from ragnexus.config import Settings

logger = logging.getLogger(__name__)


class RetrieveObservability:
    """Langfuse 可观测客户端，fire-and-forget 模式。

    所有方法不会抛出异常 — 失败时静默返回 None 并 log warning。
    """

    def __init__(self, enabled: bool, client: Langfuse | None = None) -> None:
        self._enabled = enabled
        self._client = client

    def create_trace(self, name: str, metadata: dict | None = None) -> dict | None:
        """创建 Langfuse trace。

        Returns:
            {"id": trace_id, "trace": langfuse_trace_obj}，失败或 disabled 返回 None。
        """
        if not self._enabled or not self._client:
            return None
        try:
            trace = self._client.trace(name=name, metadata=metadata)
            return {"id": trace.id, "trace": trace}
        except Exception as e:
            logger.warning(f"Failed to create Langfuse trace: {e}")
            return None

    def create_span(
        self,
        trace: dict,
        name: str,
        input_data: dict | None = None,
    ) -> dict | None:
        """在 trace 下创建子 span。

        Args:
            trace: create_trace 返回的 dict（含 "trace" 键指向 Langfuse trace 对象）。
            name: span 名称。
            input_data: span 的输入数据。

        Returns:
            {"id": span_id, "span": langfuse_span_obj}，失败或 disabled 返回 None。
        """
        if not self._enabled:
            return None
        if trace is None:
            return None
        try:
            span = trace["trace"].span(name=name, input=input_data)
            return {"id": span.id, "span": span}
        except Exception as e:
            logger.warning(f"Failed to create Langfuse span: {e}")
            return None

    def update_span(self, span: dict | None, output_data: dict | None = None) -> None:
        """更新 span 的输出数据。

        Args:
            span: create_span 返回的 dict（含 "span" 键指向 Langfuse span 对象）。
            output_data: span 的输出数据。
        """
        if not self._enabled or span is None:
            return
        try:
            span["span"].update(output=output_data)
        except Exception as e:
            logger.warning(f"Failed to update Langfuse span: {e}")

    def end_trace(self, trace: dict | None) -> None:
        """结束 trace（触发最终 flush）。

        Args:
            trace: create_trace 返回的 dict（含 "trace" 键指向 Langfuse trace 对象）。
        """
        if not self._enabled or trace is None:
            return
        try:
            trace["trace"].update()
        except Exception as e:
            logger.warning(f"Failed to end Langfuse trace: {e}")


def get_langfuse_client(settings: Settings) -> RetrieveObservability:
    """工厂函数：根据 Settings 创建 RetrieveObservability 实例。

    LANGFUSE_ENABLED=False 时返回 disabled 客户端（所有方法 noop）。
    """
    if not settings.LANGFUSE_ENABLED:
        return RetrieveObservability(enabled=False)
    client = Langfuse(
        host=settings.LANGFUSE_HOST,
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
    )
    return RetrieveObservability(enabled=True, client=client)
