"""The tenant root.

Every other organization-owned table hangs off this one. See ADR 0009 for why
Milestone 1 carries tenant scoping from the start rather than retrofitting it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.identity import Role, User
    from app.models.vendor import Vendor


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A tenant: one company's catalog, vendors, imports, and audit trail."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(nullable=False)
    slug: Mapped[str] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    users: Mapped[list[User]] = relationship(back_populates="organization")
    roles: Mapped[list[Role]] = relationship(back_populates="organization")
    vendors: Mapped[list[Vendor]] = relationship(back_populates="organization")

    __table_args__ = (
        Index("uq_organizations_slug", "slug", unique=True),
        CheckConstraint("slug = lower(slug)", name="slug_is_lowercase"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
    )
