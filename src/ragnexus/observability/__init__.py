"""RAGNexus 可观测模块 — fire-and-forget 旁路。

提供 Langfuse 可观测客户端，用于记录检索管线的 trace/span。
"""

from ragnexus.observability.langfuse_client import (
    RetrieveObservability,
    get_langfuse_client,
)

__all__ = ["RetrieveObservability", "get_langfuse_client"]
