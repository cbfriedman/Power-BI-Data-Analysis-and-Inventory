"""Per-request ambient context.

The correlation id has to reach three places that never call each other: log
lines, audit rows, and error responses. Threading it through every function
signature would be noise, so it lives in a context variable set once by the
middleware.

A ``ContextVar`` is the right tool here rather than a global: it is isolated per
task and per thread, so concurrent requests cannot read each other's id — which
matters because route handlers run in a threadpool (ADR 0008).
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("prms_request_id", default=None)


def new_request_id() -> str:
    return str(uuid.uuid4())


def set_request_id(request_id: str) -> Token[str | None]:
    """Bind a correlation id to the current context.

    Returns the token needed to restore the previous value.
    """
    return _request_id.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


def get_request_id() -> str | None:
    """The current correlation id, or None outside a request.

    Callers must tolerate ``None``: worker and CLI code writes audit rows too,
    and there is no HTTP request behind those.
    """
    return _request_id.get()
