"""Error taxonomy and centralized HTTP exception handling.

Two rules shape this module:

1. **Every** error response has the same envelope, whether it came from an
   application error, a FastAPI validation failure, or an unhandled exception.
   A client that can parse one failure can parse all of them.
2. An unhandled exception never returns a stack trace to the client in
   production. The traceback is logged server-side with the correlation id; the
   client gets that id and nothing else. Leaked tracebacks disclose file paths,
   library versions, and sometimes query fragments containing data.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import Settings
from app.core.context import get_request_id
from app.core.logging import get_logger
from app.core.middleware import REQUEST_ID_HEADER
from app.core.redaction import redact_mapping

_logger = get_logger(__name__)


class AppError(Exception):
    """Base for errors the application raises deliberately.

    Carries everything the handler needs to build a response, so route code
    raises a meaningful exception rather than assembling HTTP details inline.
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        super().__init__(self.message)


class AuthenticationError(AppError):
    """No usable credential was presented, or it failed validation."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"
    message = "Authentication is required."


class AuthorizationError(AppError):
    """The caller is known but lacks the required role."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "The requested resource does not exist."


class ConflictError(AppError):
    """The request contradicts current state — a duplicate, or a lost update."""

    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "The request conflicts with the current state of the resource."


class ValidationFailedError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_failed"
    message = "The request payload is not valid."


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"
    message = "A required dependency is unavailable."


def _with_correlation_header(headers: dict[str, str] | None) -> dict[str, str] | None:
    """Add X-Request-ID to an error response.

    The request middleware sets this header on successful responses, but an
    unhandled exception is caught further out than that, so error responses have
    to carry it themselves.
    """
    request_id = get_request_id()
    if request_id is None:
        return headers
    combined = dict(headers or {})
    combined.setdefault(REQUEST_ID_HEADER, request_id)
    return combined


def error_payload(
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the single error envelope used by every failure response."""
    body: dict[str, Any] = {"code": code, "message": message}
    request_id = get_request_id()
    if request_id is not None:
        # Given to the client so a support conversation can start with an id
        # that ties straight to the server-side logs and audit rows.
        body["request_id"] = request_id
    if details:
        body["details"] = redact_mapping(details)
    return {"error": body}


def register_exception_handlers(app: FastAPI, settings: Settings) -> None:
    """Install the handlers. Called once from the application factory."""

    async def handle_app_error(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, AppError)
        # Expected failures are logged at warning; they are not defects.
        _logger.warning(
            "request.rejected",
            error_code=exc.code,
            status_code=exc.status_code,
            detail=exc.message,
        )
        headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, AuthenticationError) else None
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(code=exc.code, message=exc.message, details=exc.details),
            headers=_with_correlation_header(headers),
        )

    async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
        """Give Starlette's own errors — 404, 405 — the same envelope."""
        assert isinstance(exc, StarletteHTTPException)
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(code=_code_for_status(exc.status_code), message=detail),
            headers=_with_correlation_header(getattr(exc, "headers", None)),
        )

    async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)
        # `errors()` can contain the offending input, which may be a credential
        # on an auth route, so the payload goes through redaction.
        fields = [
            {
                "location": list(error.get("loc", [])),
                "message": error.get("msg", ""),
                "type": error.get("type", ""),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=error_payload(
                code="validation_failed",
                message="The request payload is not valid.",
                details={"fields": fields},
            ),
            headers=_with_correlation_header(None),
        )

    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """The catch-all. This is where stack traces stop.

        The full traceback goes to the log with the correlation id. The client
        receives the id and a generic message — unless error detail is
        explicitly enabled, which the settings validator forbids in production.
        """
        _logger.exception("request.unhandled_error", error_type=type(exc).__name__)

        details: dict[str, Any] | None = None
        if settings.expose_error_details and not settings.is_production:
            details = {"exception": type(exc).__name__, "detail": str(exc)}

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_payload(
                code="internal_error",
                message="An unexpected error occurred.",
                details=details,
            ),
            headers=_with_correlation_header(None),
        )

    handlers: dict[Any, Callable[[Request, Exception], Awaitable[JSONResponse]]] = {
        AppError: handle_app_error,
        StarletteHTTPException: handle_http_exception,
        RequestValidationError: handle_validation_error,
        Exception: handle_unexpected_error,
    }
    for exception_class, handler in handlers.items():
        app.add_exception_handler(exception_class, handler)


def _code_for_status(status_code: int) -> str:
    return {
        status.HTTP_400_BAD_REQUEST: "bad_request",
        status.HTTP_401_UNAUTHORIZED: "unauthenticated",
        status.HTTP_403_FORBIDDEN: "forbidden",
        status.HTTP_404_NOT_FOUND: "not_found",
        status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
        status.HTTP_409_CONFLICT: "conflict",
        status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_failed",
        status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
    }.get(status_code, "error")
