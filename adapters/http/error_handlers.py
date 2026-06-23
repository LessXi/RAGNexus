"""Global error handlers for FastAPI — maps DomainError → JSONResponse."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from domain.errors import DomainError


def register_error_handlers(app: FastAPI) -> None:
    """Register a single handler that turns any DomainError into a
    consistent JSON error response matching the spec.

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
