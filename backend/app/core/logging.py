"""Structured JSON logging.

Application logs and the logs emitted by uvicorn and SQLAlchemy are routed
through one structlog pipeline so every line is a single JSON object with
consistent keys. A ``request_id`` bound via context variables is attached
automatically, which is what correlates an HTTP request to its log lines and,
once audit logging lands in phase 1, to its audit rows (CLAUDE.md §6).
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import Processor

from app.core.config import Settings

_STDLIB_LOGGERS_TO_TAME = ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy.engine")


def configure_logging(settings: Settings) -> None:
    """Configure structlog and the stdlib logging module.

    Safe to call more than once; later calls replace the previous configuration.
    """
    level = getattr(logging, settings.log_level, logging.INFO)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # Let these propagate to the root handler rather than writing their own
    # unstructured lines to stderr.
    for name in _STDLIB_LOGGERS_TO_TAME:
        stdlib_logger = logging.getLogger(name)
        stdlib_logger.handlers.clear()
        stdlib_logger.propagate = True


def get_logger(name: str | None = None) -> Any:
    """Return a bound structlog logger.

    The return type is intentionally ``Any``: structlog's ``BoundLogger`` gains
    its methods dynamically, so a narrower annotation would be a lie that mypy
    could not check usefully.
    """
    return structlog.stdlib.get_logger(name)
