"""Provisioning of the system roles.

The four roles in :class:`~app.core.security.RoleCode` are seeded per
organization rather than defined globally, because ``roles`` is tenant-scoped so
an organization can add its own without affecting anyone else (ADR 0009).

Seeding happens here rather than in a data migration for a practical reason: no
organization exists at migration time, and a migration that invents one would be
a fixture masquerading as schema.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import SYSTEM_ROLE_DEFINITIONS, RoleCode
from app.models.identity import Role, User, UserRole


def ensure_system_roles(session: Session, organization_id: uuid.UUID) -> dict[RoleCode, Role]:
    """Create any missing system roles for an organization. Idempotent.

    Existing rows are left alone — an organization may have renamed a role's
    display name, and overwriting that on every startup would be rude.
    """
    existing = {
        role.code: role
        for role in session.execute(
            select(Role).where(Role.organization_id == organization_id)
        ).scalars()
    }

    roles: dict[RoleCode, Role] = {}
    for code, (name, description) in SYSTEM_ROLE_DEFINITIONS.items():
        found = existing.get(code.value)
        if found is None:
            found = Role(
                organization_id=organization_id,
                code=code.value,
                name=name,
                description=description,
                is_system=True,
            )
            session.add(found)
        roles[code] = found

    session.flush()
    return roles


def assign_role(
    session: Session,
    *,
    user: User,
    role: Role,
    granted_by_user_id: uuid.UUID | None = None,
) -> UserRole:
    """Grant a role to a user. Idempotent: re-granting returns the existing row."""
    existing = session.execute(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    assignment = UserRole(
        organization_id=user.organization_id,
        user_id=user.id,
        role_id=role.id,
        granted_by_user_id=granted_by_user_id,
    )
    session.add(assignment)
    session.flush()
    return assignment
