"""The single source of "now".

Every timestamp in this system is UTC and timezone-aware (CLAUDE.md §4). Routing
all time through one function keeps that rule enforceable and makes time
freezable in tests. Do not call ``datetime.now()`` elsewhere.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)
