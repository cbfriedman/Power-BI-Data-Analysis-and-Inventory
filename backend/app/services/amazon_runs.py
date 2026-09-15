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
from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.context import get_request_id
from app.core.logging import get_logger
from app.db.transaction import transaction
from app.models.amazon import AmazonSyncRun
from app.models.enums import ActorType, AmazonSyncJobType, SyncStatus, TriggerType
from app.models.organization import Organization
from app.repositories.scoping import TenantScope
from app.services import audit

_logger = get_logger(__name__)

STALE_RUN_MESSAGE: Final = "timed out"
AUDIT_ACTION_STALE: Final = "amazon.run.timed_out"
AUDIT_ACTOR_LABEL_STALE: Final = "amazon-run-recovery"


class AmazonOrganizationError(Exception):
    """The organization the Amazon account belongs to could not be determined."""


def resolve_amazon_organization(session: Session, slug: str | None) -> uuid.UUID:
    """The organization the configured Amazon credentials belong to.

    Credentials are per deployment (one ``AMAZON_*`` set), so the jobs need
    to know which tenant to write into. ``AMAZON_ORGANIZATION_SLUG`` names
    it; while exactly one active organization exists it may be omitted.
    """
    if slug:
        found = session.execute(
            select(Organization.id).where(Organization.slug == slug, Organization.is_active)
        ).scalar_one_or_none()
        if found is None:
            raise AmazonOrganizationError(
                f"AMAZON_ORGANIZATION_SLUG {slug!r} does not name an active organization"
            )
        return found

    ids = list(session.execute(select(Organization.id).where(Organization.is_active)).scalars())
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise AmazonOrganizationError("no active organization exists yet")
    raise AmazonOrganizationError(
        f"{len(ids)} active organizations exist; set AMAZON_ORGANIZATION_SLUG to choose one"
    )


def recover_stale_runs(
    session: Session,
    organization_id: uuid.UUID,
    job_type: AmazonSyncJobType,
    *,
    now: datetime,
    timeout: timedelta,
) -> list[uuid.UUID]:
    """Close RUNNING runs older than ``timeout`` as FAILED ("timed out").

    A process that died between claiming the slot and its ``finally`` leaves
    a RUNNING row that would block every later run of the same job type
    forever. Anything RUNNING for longer than the timeout is assumed dead.
    Commits in its own transaction; returns the ids it closed.
    """
    cutoff = now - timeout
    stale = list(
        session.execute(
            TenantScope(organization_id)
            .select(AmazonSyncRun)
            .where(
                AmazonSyncRun.job_type == job_type,
                AmazonSyncRun.status == SyncStatus.RUNNING,
                AmazonSyncRun.started_at.is_not(None),
                AmazonSyncRun.started_at < cutoff,
            )
        ).scalars()
    )
    if not stale:
        return []

    with transaction(session):
        for run in stale:
            before = audit.snapshot(run)
            run.status = SyncStatus.FAILED
            run.completed_at = now
            run.error_message = STALE_RUN_MESSAGE
            run.error_details = {
                "exception": "StaleRun",
                "message": STALE_RUN_MESSAGE,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "timeout_minutes": int(timeout.total_seconds() // 60),
            }
            session.flush()
            audit.record_change(
                session,
                organization_id=organization_id,
                action=AUDIT_ACTION_STALE,
                instance=run,
                before=before,
                actor_type=ActorType.SYSTEM,
                actor_label=AUDIT_ACTOR_LABEL_STALE,
                summary=f"{job_type.value} run {run.id} marked FAILED: {STALE_RUN_MESSAGE}",
            )
            _logger.warning(
                "amazon.run.timed_out",
                run_id=str(run.id),
                job_type=job_type.value,
                started_at=run.started_at.isoformat() if run.started_at else None,
            )
    return [run.id for run in stale]


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
