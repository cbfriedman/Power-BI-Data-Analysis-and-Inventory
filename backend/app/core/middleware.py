"""HTTP middleware.

The request-correlation middleware assigns every request an id, binds it to the
logging context, echoes it back in the ``X-Request-ID`` response header, and
logs one structured line per completed request. Audit rows written in later
phases carry the same id (CLAUDE.md §6).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import new_request_id, reset_request_id, set_request_id
from app.core.logging import get_logger

REQUEST_ID_HEADER = "X-Request-ID"

_logger = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a request id to the log context and record request completion."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or new_request_id()

        # Bound in two places on purpose: structlog contextvars feed the log
        # renderer, while the plain context var is what non-logging code (the
        # audit service, error handlers) reads without importing structlog.
        token = set_request_id(request_id)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            _logger.exception("request.failed", duration_ms=duration_ms)
            structlog.contextvars.clear_contextvars()
            # Deliberately NOT reset here. Starlette's ServerErrorMiddleware sits
            # outside this one, so the 500 handler runs after this frame — it
            # still needs the id to put in the response. The context var dies
            # with the request's task, so nothing leaks between requests.
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        _logger.info(
            "request.completed",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        structlog.contextvars.clear_contextvars()
        reset_request_id(token)
        return response
