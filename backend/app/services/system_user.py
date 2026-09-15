"""The per-organization system user.

An approved mapping must name its approver (a check constraint says so), and
match priority 4 approves a listing without a person in the loop: the
catalog source already named the SKU. The approver in that case is this
user — one per organization, created on first use, with no password and no
roles, so it can be named in a row but can never sign in.
"""

from __future__ import annotations

import uuid
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import User

SYSTEM_USER_EMAIL: Final = "system@prms.internal"
SYSTEM_USER_DISPLAY_NAME: Final = "System"


def ensure_system_user(session: Session, organization_id: uuid.UUID) -> User:
    """Return the organization's system user, creating it if absent.

    Flushes so the id is available; the caller owns the transaction.
    """
    existing = session.execute(
        select(User).where(User.organization_id == organization_id, User.email == SYSTEM_USER_EMAIL)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    user = User(
        organization_id=organization_id,
        email=SYSTEM_USER_EMAIL,
        display_name=SYSTEM_USER_DISPLAY_NAME,
        password_hash=None,
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user
