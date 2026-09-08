"""``audit_events`` is append-only, enforced by the database (CLAUDE.md §6).

Application-level discipline is not enough here. An audit trail is only evidence
if it cannot be quietly rewritten — including from a psql session by someone
with the application's own credentials.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.models.enums import ActorType
from tests.integration import factories

pytestmark = pytest.mark.integration


def _make_audit_event(session: Session) -> AuditEvent:
    organization = factories.make_organization(session)
    user = factories.make_user(session, organization)
    event = AuditEvent(
        organization_id=organization.id,
        actor_type=ActorType.USER,
        actor_user_id=user.id,
        actor_label=user.email,
        action="mapping.approved",
        entity_type="vendor_product",
        entity_id=user.id,
        before={"mapping_status": "PENDING"},
        after={"mapping_status": "APPROVED"},
        changed_fields=["mapping_status"],
        request_id="req-123",
    )
    session.add(event)
    session.flush()
    return event


def test_an_audit_event_can_be_written(db_session: Session) -> None:
    event = _make_audit_event(db_session)

    assert event.before == {"mapping_status": "PENDING"}
    assert event.after == {"mapping_status": "APPROVED"}
    assert event.changed_fields == ["mapping_status"]
    assert event.occurred_at is not None


def test_an_audit_event_cannot_be_updated(db_session: Session) -> None:
    event = _make_audit_event(db_session)

    with pytest.raises(DBAPIError) as caught:
        db_session.execute(
            update(AuditEvent).where(AuditEvent.id == event.id).values(action="tampered")
        )
        db_session.flush()

    assert "append-only" in str(caught.value)


def test_an_audit_event_cannot_be_deleted(db_session: Session) -> None:
    event = _make_audit_event(db_session)

    with pytest.raises(DBAPIError) as caught:
        db_session.execute(delete(AuditEvent).where(AuditEvent.id == event.id))
        db_session.flush()

    assert "append-only" in str(caught.value)


def test_the_guard_survives_a_raw_sql_attempt(db_session: Session) -> None:
    """Not just an ORM-level convention — raw SQL is blocked too."""
    event = _make_audit_event(db_session)

    with pytest.raises(DBAPIError):
        db_session.execute(
            text("update audit_events set action = 'tampered' where id = :id"),
            {"id": event.id},
        )
        db_session.flush()


def test_a_user_action_must_name_the_user(db_session: Session) -> None:
    organization = factories.make_organization(db_session)
    event = AuditEvent(
        organization_id=organization.id,
        actor_type=ActorType.USER,
        action="vendor.created",
        entity_type="vendor",
    )
    db_session.add(event)

    with pytest.raises(DBAPIError):
        db_session.flush()


def test_a_system_action_must_not_borrow_a_user(db_session: Session) -> None:
    organization = factories.make_organization(db_session)
    user = factories.make_user(db_session, organization)
    event = AuditEvent(
        organization_id=organization.id,
        actor_type=ActorType.SYSTEM,
        actor_user_id=user.id,
        action="sync.started",
        entity_type="nineyard_sync_run",
    )
    db_session.add(event)

    with pytest.raises(DBAPIError):
        db_session.flush()


def test_a_system_action_is_accepted_without_a_user(db_session: Session) -> None:
    organization = factories.make_organization(db_session)
    event = AuditEvent(
        organization_id=organization.id,
        actor_type=ActorType.SYSTEM,
        actor_label="catalog-sync",
        action="sync.started",
        entity_type="nineyard_sync_run",
    )
    db_session.add(event)
    db_session.flush()

    stored = db_session.execute(select(AuditEvent).where(AuditEvent.id == event.id)).scalar_one()
    assert stored.actor_user_id is None
    assert stored.actor_label == "catalog-sync"
