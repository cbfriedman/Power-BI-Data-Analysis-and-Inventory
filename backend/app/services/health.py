"""Health and readiness logic.

Services hold behaviour and coordinate repositories. They return plain results;
translating a result into an HTTP status code is the API layer's job.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import health as health_repository

DependencyStatus = Literal["ok", "unavailable"]

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    """Outcome of a readiness probe."""

    database: DependencyStatus
    detail: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.database == "ok"


def check_readiness(session: Session) -> ReadinessResult:
    """Confirm the service can reach every dependency it needs to serve traffic.

    Today that is PostgreSQL alone. A failure is reported, not raised, so the
    probe can distinguish "the process is up but degraded" from "the process is
    gone" (AC-0.5).
    """
    try:
        health_repository.ping(session)
    except SQLAlchemyError as exc:
        _logger.warning("health.database_unavailable", error=str(exc))
        return ReadinessResult(database="unavailable", detail="database unreachable")

    return ReadinessResult(database="ok")
