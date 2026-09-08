"""Health endpoint response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LivenessResponse(BaseModel):
    """Response for the unversioned liveness probe."""

    status: Literal["ok"] = "ok"
    service: str = Field(description="Application name, from configuration.")
    checked_at: datetime = Field(description="UTC timestamp of the check.")


class DependencyHealth(BaseModel):
    """Status of a single downstream dependency."""

    name: str
    status: Literal["ok", "unavailable"]
    detail: str | None = None


class ReadinessResponse(BaseModel):
    """Response for the versioned readiness probe."""

    status: Literal["ok", "degraded"]
    service: str
    environment: str
    api_version: str = "v1"
    checked_at: datetime = Field(description="UTC timestamp of the check.")
    dependencies: list[DependencyHealth]
