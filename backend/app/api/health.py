"""Unversioned liveness probe.

This is the one route permitted outside ``/api/v1`` (CLAUDE.md §4): container
and orchestrator probes need a stable path that survives API versioning. It
answers "is this process alive", nothing more, and deliberately touches no
dependency — a database outage must not cause the container to be killed and
restarted, which would help nobody.

Readiness, which does check dependencies, lives at ``/api/v1/health``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.clock import utc_now
from app.core.config import Settings, get_settings
from app.schemas.health import LivenessResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=LivenessResponse,
    summary="Liveness probe",
)
def liveness(settings: Settings = Depends(get_settings)) -> LivenessResponse:
    """Return 200 whenever the process is running."""
    return LivenessResponse(service=settings.app_name, checked_at=utc_now())
