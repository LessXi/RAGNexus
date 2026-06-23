"""Global error handlers for FastAPI — maps DomainError → JSONResponse."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from domain.errors import DomainError


def register_error_handlers(app: FastAPI) -> None:
    """Register two handlers that turn DomainError and RequestValidationError
    into consistent JSON error responses matching the spec.

    Response shape::

        {"code": int, "data": None, "message": str, "errors": list[dict]}
    """

    @app.exception_handler(DomainError)
    async def _domain_error_handler(
        request: Request, exc: DomainError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "code": exc.code,
                "data": None,
                "message": exc.message_text or exc.message,
                "errors": exc.errors,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError,
    ) -> JSONResponse:
        errors = []
        for e in exc.errors():
            errors.append({
                "field": ".".join(str(loc) for loc in e.get("loc", []) if loc != "body"),
                "reason": e.get("msg", ""),
            })
        return JSONResponse(
            status_code=422,
            content={
                "code": 1000,
                "data": None,
                "message": "参数错误",
                "errors": errors,
            },
        )
