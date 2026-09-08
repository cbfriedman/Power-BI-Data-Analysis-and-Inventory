"""Column mixins shared by every model.

Applying these consistently is what makes the schema invariants in
[docs/acceptance-criteria.md](../../../docs/acceptance-criteria.md) AC-1.1
through AC-1.4 testable: a test can assert that *every* table has a UUID primary
key, timezone-aware timestamps, and — where the table is organization-owned — an
``organization_id``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, func, text
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


def pg_enum(enum_cls: type, name: str) -> SAEnum:
    """Build a native PostgreSQL enum from a Python enum.

    ``values_callable`` stores the member *value* rather than the member name.
    They are identical throughout ``app.models.enums``, but pinning it means a
    later rename of a member cannot silently change what is written to the
    database.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=True,
        create_type=True,
        values_callable=lambda e: [member.value for member in e],
    )


class UUIDPrimaryKeyMixin:
    """Immutable internal UUID primary key.

    Generated in Python so a new object carries its identity before flush, and
    also defaulted server-side so rows inserted by raw SQL or a migration get a
    valid key. The value is never reused and never updated (ADR 0002).
    """

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """UTC creation and modification timestamps.

    ``TIMESTAMPTZ`` via the base's ``type_annotation_map``. PostgreSQL stores
    these in UTC regardless of the session timezone, so AC-1.3 holds even when a
    client connects from another zone.
    """

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class OrganizationScopedMixin:
    """Tenant ownership.

    Every organization-owned table carries this. ``RESTRICT`` is deliberate: an
    organization with any data cannot be deleted out from under it. Removing a
    tenant is an explicit, ordered operation, not a cascade nobody reviewed
    (ADR 0009).
    """

    @declared_attr
    def organization_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(
            ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
