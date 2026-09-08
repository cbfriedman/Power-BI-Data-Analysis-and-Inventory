"""The audit service.

Every important data change is recorded here (CLAUDE.md §6). Three properties
matter, and each is enforced rather than assumed:

* **Transactional.** ``record`` adds the row to the caller's session and does
  not commit. Wrap the change and its audit entry in one
  :func:`app.db.transaction.transaction` block and they commit or roll back
  together — an audit row cannot survive a rollback, and a committed change
  cannot lack one (ADR 0006).
* **Correlated.** The request id is read from the ambient context, so a support
  question that starts with a request id reaches the log lines *and* the audit
  rows for that request.
* **Clean.** ``before`` and ``after`` are redacted before they are stored. An
  audit trail that captures a password hash or a token has traded one problem
  for another (AC-12.6).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.core.context import get_request_id
from app.core.redaction import is_sensitive_key, redact_mapping
from app.core.security import Principal
from app.db.base import Base
from app.models.audit import AuditEvent
from app.models.enums import ActorType

# Columns that are noise in a diff: they change on every write and say nothing
# about intent.
_UNINTERESTING_COLUMNS: frozenset[str] = frozenset({"created_at", "updated_at"})


def snapshot(instance: Base, *, exclude: frozenset[str] | None = None) -> dict[str, Any]:
    """Capture a model's column values as a JSON-safe mapping.

    Only mapped columns — relationships are followed nowhere, because an audit
    row should describe one record, not drag in half the object graph.
    Sensitive columns are dropped entirely rather than masked, so they never
    reach the database in any form.
    """
    skip = (exclude or frozenset()) | _UNINTERESTING_COLUMNS
    mapper = sa_inspect(type(instance))

    captured: dict[str, Any] = {}
    for column in mapper.columns:
        name = column.key
        if name in skip or is_sensitive_key(name):
            continue
        captured[name] = _to_jsonable(getattr(instance, name, None))
    return captured


def changed_fields(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> list[str]:
    """Field names whose value differs between the two states.

    A creation reports every field in ``after``; a deletion, every field in
    ``before``.
    """
    if before is None and after is None:
        return []
    if before is None:
        return sorted(after or {})
    if after is None:
        return sorted(before)

    keys = set(before) | set(after)
    return sorted(key for key in keys if before.get(key) != after.get(key))


def record(
    session: Session,
    *,
    organization_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    actor: Principal | None = None,
    actor_type: ActorType | None = None,
    actor_label: str | None = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    summary: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditEvent:
    """Add one audit entry to ``session``.

    Does not commit — that is the caller's transaction to control.

    ``actor`` names a person. Omit it for work with no human behind it and pass
    ``actor_type`` plus an ``actor_label`` naming the process, which is what the
    check constraint on the table requires.
    """
    resolved_label_value: str | None
    if actor is not None:
        resolved_type = ActorType.USER
        actor_user_id: uuid.UUID | None = actor.user_id
        resolved_label_value = actor_label or actor.email
    else:
        resolved_type = actor_type or ActorType.SYSTEM
        if resolved_type is ActorType.USER:
            raise ValueError("actor_type USER requires an actor; pass one or use SYSTEM/WORKER")
        actor_user_id = None
        resolved_label_value = actor_label

    event = AuditEvent(
        organization_id=organization_id,
        actor_type=resolved_type,
        actor_user_id=actor_user_id,
        actor_label=resolved_label_value,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=redact_mapping(before) if before is not None else None,
        after=redact_mapping(after) if after is not None else None,
        changed_fields=changed_fields(before, after) or None,
        request_id=get_request_id(),
        ip_address=ip_address,
        user_agent=user_agent,
        summary=summary,
    )
    session.add(event)
    return event


def record_change(
    session: Session,
    *,
    organization_id: uuid.UUID,
    action: str,
    instance: Base,
    before: Mapping[str, Any] | None,
    actor: Principal | None = None,
    **kwargs: Any,
) -> AuditEvent:
    """Record a change to a model instance, snapshotting its current state.

    Capture ``before`` with :func:`snapshot` prior to mutating, then call this
    afterwards; the ``after`` state and the changed-field list are derived.
    """
    entity_id = getattr(instance, "id", None)
    return record(
        session,
        organization_id=organization_id,
        action=action,
        entity_type=instance.__tablename__,
        entity_id=entity_id if isinstance(entity_id, uuid.UUID) else None,
        actor=actor,
        before=before,
        after=snapshot(instance),
        **kwargs,
    )


def _to_jsonable(value: Any) -> Any:
    """Coerce a column value into something JSONB accepts."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_to_jsonable(item) for item in value]
    # datetime, Decimal, Enum and anything else become their string form, which
    # is readable in the trail and stable to compare.
    return str(value)
