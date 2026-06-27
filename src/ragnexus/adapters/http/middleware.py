"""HTTP 请求日志中间件 — LoggingMiddleware。

通过 Starlette BaseHTTPMiddleware 拦截所有 HTTP 请求，
记录 API_REQUEST / API_RESPONSE 事件，注入 req_id 到 ContextVar。
"""

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from ragnexus.core.logger import clear_log_context, logger, set_log_context


class LoggingMiddleware(BaseHTTPMiddleware):
    """为每个 HTTP 请求记录结构化日志。

    功能：
    - 生成/复用 X-Request-ID
    - 注入 ContextVar（req_id / client_ip）
    - 记录 API_REQUEST（method / path / body）
    - 记录 API_RESPONSE（status / cost_ms）
    - 请求结束后清理 ContextVar
    """

    async def dispatch(self, request: Request, call_next):
        # 1. 生成或复用 req_id
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]

        # 2. 注入 ContextVar
        client_ip = request.client.host if request.client else None
        set_log_context(req_id=req_id, client_ip=client_ip or "")

        # 3. 记录 API_REQUEST
        method = request.method
        path = request.url.path
        content_type = request.headers.get("content-type", "")

        body = None
        if "application/json" in content_type:
            body_bytes = await request.body()
            body = body_bytes.decode("utf-8", errors="replace")[:500]

            # 回填 body 给下游路由
            async def receive():
                return {
                    "type": "http.request",
                    "body": body_bytes,
                    "more_body": False,
                }

            request = Request(request.scope, receive)
        elif "multipart" in content_type:
            body = "<multipart>"

        logger.info(
            "",
            extra={
                "event_type": "API_REQUEST",
                "method": method,
                "path": path,
                "body": body or "",
            },
        )

        # 4. 调用路由（try/finally 确保异常路径也记录 API_RESPONSE 并清理上下文）
        t0 = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            cost_ms = (time.perf_counter() - t0) * 1000
            status = response.status_code if response is not None else 500

            # 5. 记录 API_RESPONSE
            logger.info(
                "",
                extra={
                    "event_type": "API_RESPONSE",
                    "status": status,
                    "cost_ms": round(cost_ms, 2),
                },
            )

            # 6. 清理 ContextVar
            clear_log_context()
