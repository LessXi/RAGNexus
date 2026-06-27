"""Global error handlers for FastAPI — maps AppError → JSONResponse."""

import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.core.logger import logger


def register_error_handlers(app: FastAPI) -> None:
    """Register two handlers that turn AppError and RequestValidationError
    into consistent JSON error responses matching the spec.

    Response shape::

        {"code": int, "data": None, "message": str, "errors": list[dict]}
    """

    @app.exception_handler(AppError)
    async def _domain_error_handler(
        request: Request,
        exc: AppError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "code": exc.code,
                "data": None,
                "message": exc.message,
                "errors": exc.errors,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors = []
        for e in exc.errors():
            errors.append(
                {
                    "field": ".".join(str(loc) for loc in e.get("loc", []) if loc != "body"),
                    "reason": e.get("msg", ""),
                }
            )
        return JSONResponse(
            status_code=422,
            content={
                "code": ErrorCode.PARAM_ERROR.code,
                "data": None,
                "message": "参数错误",
                "errors": errors,
            },
        )

    @app.exception_handler(Exception)
    async def _unexpected_error_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        # 排除 AppError（已有专门 handler）
        if isinstance(exc, AppError):
            raise exc

        logger.error(
            "",
            extra={
                "event_type": "SYSTEM_ERROR",
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )

        return JSONResponse(
            status_code=500,
            content={
                "code": ErrorCode.SERVER_ERROR.code,
                "data": None,
                "message": ErrorCode.SERVER_ERROR.msg,
                "errors": [],
            },
        )
