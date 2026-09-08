"""The audit service writes usable records (requirement 11, CLAUDE.md §6).

Three things are worth proving beyond "a row appears": the entry commits with
the change it describes, secrets never reach the payload, and the correlation id
survives the trip from middleware to database row.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.context import reset_request_id, set_request_id
from app.core.security import Principal, RoleCode
from app.db.transaction import transaction
from app.models import AuditEvent, Vendor
from app.models.enums import ActorType
from app.services import audit
from app.services.roles import assign_role, ensure_system_roles
from tests.integration import factories

pytestmark = pytest.mark.integration


class TestRecordingEvents:
    def test_a_user_action_is_recorded(self, db_session: Session) -> None:
        organization = factories.make_organization(db_session)
        user = factories.make_user(db_session, organization)
        actor = Principal(
            user_id=user.id,
            organization_id=organization.id,
            email=user.email,
            display_name=user.display_name,
            roles=frozenset({RoleCode.DATA_OPERATOR}),
        )
        vendor = factories.make_vendor(db_session, organization)

        event = audit.record(
            db_session,
            organization_id=organization.id,
            action="vendor.created",
            entity_type="vendors",
            entity_id=vendor.id,
            actor=actor,
            after={"code": vendor.code, "name": vendor.name},
            summary="Vendor created during onboarding.",
        )
        db_session.flush()

        assert event.actor_type is ActorType.USER
        assert event.actor_user_id == user.id
        assert event.actor_label == user.email
        assert event.action == "vendor.created"
        assert event.entity_id == vendor.id
        assert event.after == {"code": vendor.code, "name": vendor.name}
        assert event.occurred_at is not None

    def test_a_system_action_needs_no_user(self, db_session: Session) -> None:
        organization = factories.make_organization(db_session)

        event = audit.record(
            db_session,
            organization_id=organization.id,
            action="sync.started",
            entity_type="nineyard_sync_runs",
            actor_type=ActorType.SYSTEM,
            actor_label="catalog-sync",
        )
        db_session.flush()

        assert event.actor_user_id is None
        assert event.actor_label == "catalog-sync"

    def test_claiming_a_user_action_without_an_actor_is_a_programming_error(
        self, db_session: Session
    ) -> None:
        """Caught in Python, before the database check constraint has to."""
        organization = factories.make_organization(db_session)

        with pytest.raises(ValueError, match="requires an actor"):
            audit.record(
                db_session,
                organization_id=organization.id,
                action="vendor.created",
                entity_type="vendors",
                actor_type=ActorType.USER,
            )


class TestChangeTracking:
    def test_changed_fields_are_derived_from_the_diff(self, db_session: Session) -> None:
        organization = factories.make_organization(db_session)
        vendor = factories.make_vendor(db_session, organization, name="Old Name")
        before = audit.snapshot(vendor)

        vendor.name = "New Name"
        vendor.is_active = False
        db_session.flush()

        event = audit.record_change(
            db_session,
            organization_id=organization.id,
            action="vendor.updated",
            instance=vendor,
            before=before,
        )
        db_session.flush()

        assert event.changed_fields is not None
        assert set(event.changed_fields) == {"name", "is_active"}
        assert event.before is not None
        assert event.before["name"] == "Old Name"
        assert event.after is not None
        assert event.after["name"] == "New Name"

    def test_a_creation_reports_every_field(self, db_session: Session) -> None:
        assert audit.changed_fields(None, {"code": "ACME", "name": "Acme"}) == ["code", "name"]

    def test_timestamps_are_excluded_from_diffs(self, db_session: Session) -> None:
        """They change on every write and say nothing about intent."""
        organization = factories.make_organization(db_session)
        vendor = factories.make_vendor(db_session, organization)

        captured = audit.snapshot(vendor)

        assert "created_at" not in captured
        assert "updated_at" not in captured

    def test_a_snapshot_is_json_safe(self, db_session: Session) -> None:
        """UUIDs and enums must survive the trip into JSONB."""
        organization = factories.make_organization(db_session)
        vendor = factories.make_vendor(db_session, organization)

        captured = audit.snapshot(vendor)

        assert captured["id"] == str(vendor.id)
        assert captured["status"] == "ACTIVE"


class TestSecretsNeverReachTheTrail:
    def test_sensitive_keys_are_redacted_in_payloads(self, db_session: Session) -> None:
        organization = factories.make_organization(db_session)

        event = audit.record(
            db_session,
            organization_id=organization.id,
            action="integration.configured",
            entity_type="vendors",
            actor_type=ActorType.SYSTEM,
            actor_label="setup",
            after={"endpoint": "https://api.example.test", "api_key": "sk-live-must-not-store"},
        )
        db_session.flush()

        assert event.after is not None
        assert event.after["api_key"] == "***REDACTED***"
        assert event.after["endpoint"] == "https://api.example.test"

    def test_a_password_hash_is_never_snapshotted(self, db_session: Session) -> None:
        """The column exists on users; it must not be copied into the trail."""
        organization = factories.make_organization(db_session)
        user = factories.make_user(db_session, organization, password_hash="argon2-hash-value")

        captured = audit.snapshot(user)

        assert "password_hash" not in captured
        assert captured["email"] == user.email


class TestCorrelation:
    def test_the_request_id_is_carried_onto_the_row(self, db_session: Session) -> None:
        """One id ties a support question to logs and audit rows alike."""
        organization = factories.make_organization(db_session)
        token = set_request_id("req-correlation-test")
        try:
            event = audit.record(
                db_session,
                organization_id=organization.id,
                action="vendor.created",
                entity_type="vendors",
                actor_type=ActorType.SYSTEM,
                actor_label="test",
            )
            db_session.flush()
        finally:
            reset_request_id(token)

        assert event.request_id == "req-correlation-test"

    def test_recording_outside_a_request_is_allowed(self, db_session: Session) -> None:
        """Worker and CLI code writes audit rows with no HTTP request behind it."""
        organization = factories.make_organization(db_session)

        event = audit.record(
            db_session,
            organization_id=organization.id,
            action="job.started",
            entity_type="import_jobs",
            actor_type=ActorType.WORKER,
            actor_label="import-worker",
        )
        db_session.flush()

        assert event.request_id is None


class TestTransactionalIntegrity:
    """ADR 0006: the audit row and the change it describes are one unit."""

    def test_both_commit_together(self, db_session: Session) -> None:
        organization = factories.make_organization(db_session)
        db_session.commit()

        with transaction(db_session):
            vendor = factories.make_vendor(db_session, organization, code="TOGETHER")
            audit.record(
                db_session,
                organization_id=organization.id,
                action="vendor.created",
                entity_type="vendors",
                entity_id=vendor.id,
                actor_type=ActorType.SYSTEM,
                actor_label="test",
            )

        assert db_session.get(Vendor, vendor.id) is not None
        assert self._audit_count(db_session, "vendor.created") == 1

    def test_a_rollback_leaves_no_audit_row_behind(self, db_session: Session) -> None:
        """An entry describing a change that never happened would be a lie."""
        organization = factories.make_organization(db_session)
        db_session.commit()
        before = self._audit_count(db_session, "vendor.created")

        with pytest.raises(RuntimeError), transaction(db_session):
            vendor = factories.make_vendor(db_session, organization, code="DOOMED")
            audit.record(
                db_session,
                organization_id=organization.id,
                action="vendor.created",
                entity_type="vendors",
                entity_id=vendor.id,
                actor_type=ActorType.SYSTEM,
                actor_label="test",
            )
            raise RuntimeError("failure after both writes")

        assert self._audit_count(db_session, "vendor.created") == before
        assert (
            db_session.execute(select(Vendor).where(Vendor.code == "DOOMED")).scalar_one_or_none()
            is None
        )

    @staticmethod
    def _audit_count(session: Session, action: str) -> int:
        return session.execute(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action)
        ).scalar_one()


class TestSystemRoles:
    def test_the_four_system_roles_are_seeded(self, db_session: Session) -> None:
        organization = factories.make_organization(db_session)

        roles = ensure_system_roles(db_session, organization.id)

        assert set(roles) == {
            RoleCode.ADMIN,
            RoleCode.PURCHASING_MANAGER,
            RoleCode.DATA_OPERATOR,
            RoleCode.VIEWER,
        }
        assert all(role.is_system for role in roles.values())

    def test_seeding_twice_creates_nothing_new(self, db_session: Session) -> None:
        organization = factories.make_organization(db_session)

        first = ensure_system_roles(db_session, organization.id)
        second = ensure_system_roles(db_session, organization.id)

        assert {role.id for role in first.values()} == {role.id for role in second.values()}

    def test_assigning_a_role_twice_is_idempotent(self, db_session: Session) -> None:
        organization = factories.make_organization(db_session)
        user = factories.make_user(db_session, organization)
        roles = ensure_system_roles(db_session, organization.id)

        first = assign_role(db_session, user=user, role=roles[RoleCode.VIEWER])
        second = assign_role(db_session, user=user, role=roles[RoleCode.VIEWER])

        assert first.id == second.id
