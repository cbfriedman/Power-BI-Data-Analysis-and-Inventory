"""Amazon SP-API integration — read-only, behind an anti-corruption layer.

Admitted to Milestone 1 by ADR 0011. Nothing in this package can write to
Amazon: :class:`AmazonClient` exposes five read operations and no generic call
method, and the library's credentials dict is built at one boundary and never
stored. No SP-API field name leaves :mod:`app.integrations.amazon.dtos`.
"""

from app.integrations.amazon.client import (
    RETRYABLE_EXCEPTIONS,
    AmazonClient,
    AmazonConfig,
    CredentialCheck,
    resolve_marketplace,
)
from app.integrations.amazon.dtos import InventorySummary, ReportRequest, ReportStatus
from app.integrations.amazon.errors import (
    AmazonAuthError,
    AmazonConfigurationError,
    AmazonError,
    AmazonRateLimited,
    AmazonReportFailed,
    AmazonTransientError,
)

__all__ = [
    "RETRYABLE_EXCEPTIONS",
    "AmazonAuthError",
    "AmazonClient",
    "AmazonConfig",
    "AmazonConfigurationError",
    "AmazonError",
    "AmazonRateLimited",
    "AmazonReportFailed",
    "AmazonTransientError",
    "CredentialCheck",
    "InventorySummary",
    "ReportRequest",
    "ReportStatus",
    "resolve_marketplace",
]
