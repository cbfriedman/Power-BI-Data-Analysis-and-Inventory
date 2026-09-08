"""Versioned readiness probe.

Unlike the unversioned liveness probe, this one confirms the API can actually
serve traffic: it reaches the database and reports the result. A degraded
dependency returns 503 so load balancers stop routing to this instance while
leaving the container running (AC-0.5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings
from app.core.clock import utc_now
from app.core.config import Settings
from app.db.session import get_db
from app.schemas.health import DependencyHealth, ReadinessResponse
from app.services import health as health_service

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={503: {"description": "A required dependency is unavailable."}},
)
def readiness(
    response: Response,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> ReadinessResponse:
    """Report whether the API and its dependencies are ready to serve."""
    result = health_service.check_readiness(session)

    if not result.is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ok" if result.is_ready else "degraded",
        service=settings.app_name,
        environment=settings.app_env,
        checked_at=utc_now(),
        dependencies=[
            DependencyHealth(
                name="postgresql",
                status=result.database,
                detail=result.detail,
            )
        ],
    )
