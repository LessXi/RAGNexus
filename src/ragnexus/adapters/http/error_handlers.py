"""Global error handlers for FastAPI — maps AppError → JSONResponse."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ragnexus.core.errors import AppError, ErrorCode


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
