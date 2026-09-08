"""The append-only audit trail.

Every important data change is recorded here with actor, action, entity, UTC
timestamp, and structured before/after state (CLAUDE.md §6).

"Append-only" is enforced by the database, not by convention: the migration adds
a trigger that rejects any UPDATE or DELETE on this table. An audit trail that
can be quietly edited is not evidence of anything.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ActorType
from app.models.mixins import (
    OrganizationScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    pg_enum,
)

if TYPE_CHECKING:
    from app.models.identity import User


class AuditEvent(UUIDPrimaryKeyMixin, OrganizationScopedMixin, TimestampMixin, Base):
    """One recorded change.

    The row is written inside the same transaction as the change it describes,
    so an audit entry cannot survive a rollback and a committed change cannot
    lack one (ADR 0006).
    """

    __tablename__ = "audit_events"

    actor_type: Mapped[ActorType] = mapped_column(pg_enum(ActorType, "actor_type"), nullable=False)
    # NULL for SYSTEM and WORKER actors.
    #
    # RESTRICT, not SET NULL. SET NULL would require PostgreSQL to UPDATE this
    # table when a user row is deleted, which the append-only trigger correctly
    # refuses — so the delete would fail anyway, with a confusing error. RESTRICT
    # states the real rule plainly: a user who has acted cannot be deleted.
    # Deactivate them instead, as with every other entity here.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    # Human-readable actor label, kept even when actor_user_id is nulled out, so
    # a historical entry never becomes anonymous.
    actor_label: Mapped[str | None] = mapped_column(nullable=True)

    # Dotted verb, e.g. "vendor.created", "mapping.approved".
    action: Mapped[str] = mapped_column(nullable=False)
    entity_type: Mapped[str] = mapped_column(nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    before: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    changed_fields: Mapped[list[str] | None] = mapped_column(nullable=True)

    # Correlates an HTTP request to its audit rows and its log lines.
    request_id: Mapped[str | None] = mapped_column(nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(nullable=True)
    summary: Mapped[str | None] = mapped_column(nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))

    actor: Mapped[User | None] = relationship()

    __table_args__ = (
        # "What happened to this record?" — the primary audit question.
        Index(
            "ix_audit_events_entity",
            "organization_id",
            "entity_type",
            "entity_id",
            "occurred_at",
        ),
        # Event-timestamp search across the whole tenant.
        Index(
            "ix_audit_events_organization_id_occurred_at",
            "organization_id",
            "occurred_at",
        ),
        Index(
            "ix_audit_events_actor_occurred_at",
            "organization_id",
            "actor_user_id",
            "occurred_at",
            postgresql_where=text("actor_user_id is not null"),
        ),
        Index("ix_audit_events_organization_id_action", "organization_id", "action"),
        Index(
            "ix_audit_events_request_id",
            "request_id",
            postgresql_where=text("request_id is not null"),
        ),
        CheckConstraint("length(trim(action)) > 0", name="action_not_blank"),
        CheckConstraint("length(trim(entity_type)) > 0", name="entity_type_not_blank"),
        # A user action must name the user; a system or worker action must not
        # borrow one.
        CheckConstraint(
            "(actor_type = 'USER' and actor_user_id is not null)"
            " or (actor_type <> 'USER' and actor_user_id is null)",
            name="actor_matches_actor_type",
        ),
    )
