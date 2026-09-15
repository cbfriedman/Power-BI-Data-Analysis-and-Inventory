"""Run bookkeeping shared by every Amazon ingestion job.

Each job — orders, inventory, listings — does different work but records it
the same way: claim the ``RUNNING`` slot in its own transaction, do the
work, close the run with counts and an audit event in one transaction, and
on any failure close it as ``FAILED`` with the exception recorded. These
three functions are that shape; the services own the ``try/except/finally``
around them because the work in between is theirs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.context import get_request_id
from app.core.logging import get_logger
from app.db.transaction import transaction
from app.models.amazon import AmazonSyncRun
from app.models.enums import ActorType, AmazonSyncJobType, SyncStatus, TriggerType
from app.services import audit

_logger = get_logger(__name__)


class SyncAlreadyRunning(Exception):  # noqa: N818 — a state, not a fault
    """Another run of the same job type is still RUNNING for this organization."""


def open_run(
    session: Session,
    *,
    organization_id: uuid.UUID,
    job_type: AmazonSyncJobType,
    trigger_type: TriggerType,
    marketplace_id: str,
    started_at: datetime,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    triggered_by_user_id: uuid.UUID | None = None,
) -> AmazonSyncRun:
    """Claim the RUNNING slot in its own transaction, released immediately.

    The partial unique index on (organization_id, job_type) WHERE RUNNING is
    the lock; an IntegrityError here means another run holds it.
    """
    run = AmazonSyncRun(
        organization_id=organization_id,
        job_type=job_type,
        status=SyncStatus.RUNNING,
        trigger_type=trigger_type,
        window_start=window_start,
        window_end=window_end,
        marketplace_id=marketplace_id,
        started_at=started_at,
        triggered_by_user_id=triggered_by_user_id,
        request_id=get_request_id(),
    )
    try:
        with transaction(session):
            session.add(run)
    except IntegrityError as exc:
        raise SyncAlreadyRunning(
            f"a {job_type.value} run is already RUNNING for organization {organization_id}"
        ) from exc
    _logger.info(
        "amazon.run.started",
        run_id=str(run.id),
        job_type=job_type.value,
        organization_id=str(organization_id),
        trigger_type=trigger_type.value,
    )
    return run


def close_run(
    session: Session,
    run: AmazonSyncRun,
    *,
    status: SyncStatus,
    audit_action: str,
    actor_label: str,
    **fields: Any,
) -> None:
    """Set the final state and audit it. The caller owns the transaction."""
    for name, value in fields.items():
        setattr(run, name, value)
    run.status = status
    session.flush()
    audit.record(
        session,
        organization_id=run.organization_id,
        action=audit_action,
        entity_type=AmazonSyncRun.__tablename__,
        entity_id=run.id,
        actor_type=ActorType.SYSTEM,
        actor_label=actor_label,
        after=audit.snapshot(run),
        summary=(
            f"Amazon {run.job_type.value.lower()} sync {status.value.lower()}: "
            f"{run.rows_seen} rows seen, {run.rows_created} created, "
            f"{run.rows_updated} updated, {run.rows_unchanged} unchanged, "
            f"{run.rows_failed} failed"
        ),
    )


def fail_run(
    session: Session,
    run: AmazonSyncRun,
    failure: BaseException | None,
    *,
    completed_at: datetime,
    audit_action: str,
    actor_label: str,
) -> None:
    """Close a run as FAILED after whatever went wrong, in a fresh transaction.

    The session may be mid-failure; it is rolled back first so the final
    update can commit. The exception itself is not re-raised here — the
    caller is already propagating it.
    """
    session.rollback()
    error_type = type(failure).__name__ if failure is not None else "Unknown"
    error_message = str(failure) if failure is not None else "run ended without completing"
    _logger.error(
        "amazon.run.failed",
        run_id=str(run.id),
        job_type=run.job_type.value,
        error_type=error_type,
        error_message=error_message,
    )
    try:
        with transaction(session):
            run = session.merge(run)
            close_run(
                session,
                run,
                status=SyncStatus.FAILED,
                audit_action=audit_action,
                actor_label=actor_label,
                completed_at=completed_at,
                error_message=error_message[:1000],
                error_details={"exception": error_type, "message": error_message},
            )
    except Exception:
        # Nothing more can be done from here; the original failure is what
        # the caller sees, and this one is in the log.
        _logger.exception("amazon.run.fail_record_failed", run_id=str(run.id))
