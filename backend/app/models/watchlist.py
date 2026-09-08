"""The out-of-stock watchlist and its status history.

The watchlist is a *buying intent* list, not a report of everything with zero
inventory. A row means "we want to purchase this product; tell us when a vendor
has it." Products with no stock that nobody wants to buy never appear here.

``oos_watchlist.current_status`` is the indexed answer to "what is watched and
currently out of stock". ``oos_status_history`` is the append-only trail of how
it got there.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Numeric, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import OosStatus, WatchlistPriority
from app.models.mixins import (
    OrganizationScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    pg_enum,
)

if TYPE_CHECKING:
    from app.models.catalog import Product
    from app.models.identity import User
    from app.models.inventory import VendorInventorySnapshot
    from app.models.vendor import Vendor


class OosWatchlistEntry(UUIDPrimaryKeyMixin, OrganizationScopedMixin, TimestampMixin, Base):
    """A product the company wants to buy when it becomes available.

    ``vendor_id`` is optional: NULL watches every vendor for that product, a
    value watches one specific vendor.
    """

    __tablename__ = "oos_watchlist"

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=True
    )

    reason: Mapped[str | None] = mapped_column(nullable=True)
    priority: Mapped[WatchlistPriority] = mapped_column(
        pg_enum(WatchlistPriority, "watchlist_priority"),
        nullable=False,
        server_default=WatchlistPriority.NORMAL.value,
    )
    # Buying intent, which is what distinguishes this from a zero-stock report.
    desired_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    max_unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)

    current_status: Mapped[OosStatus] = mapped_column(
        pg_enum(OosStatus, "oos_status"),
        nullable=False,
        server_default=OosStatus.UNKNOWN.value,
    )
    current_status_changed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    added_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    deactivated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(nullable=True)

    product: Mapped[Product] = relationship()
    vendor: Mapped[Vendor | None] = relationship()
    added_by: Mapped[User | None] = relationship(foreign_keys=[added_by_user_id])
    deactivated_by: Mapped[User | None] = relationship(foreign_keys=[deactivated_by_user_id])
    status_history: Mapped[list[OosStatusHistory]] = relationship(
        back_populates="watchlist_entry", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Two partial indexes rather than one: in PostgreSQL NULL <> NULL, so a
        # single unique index over a nullable vendor_id would let unlimited
        # duplicate all-vendor watches through.
        Index(
            "uq_oos_watchlist_active_product_all_vendors",
            "organization_id",
            "product_id",
            unique=True,
            postgresql_where=text("is_active and vendor_id is null"),
        ),
        Index(
            "uq_oos_watchlist_active_product_vendor",
            "organization_id",
            "product_id",
            "vendor_id",
            unique=True,
            postgresql_where=text("is_active and vendor_id is not null"),
        ),
        # OOS-status search: what is watched and currently out of stock.
        Index(
            "ix_oos_watchlist_organization_id_current_status",
            "organization_id",
            "current_status",
            postgresql_where=text("is_active"),
        ),
        Index(
            "ix_oos_watchlist_organization_id_priority",
            "organization_id",
            "priority",
            postgresql_where=text("is_active"),
        ),
        Index("ix_oos_watchlist_product_id", "product_id"),
        CheckConstraint(
            "desired_quantity is null or desired_quantity > 0",
            name="desired_quantity_positive",
        ),
        CheckConstraint(
            "max_unit_cost is null or max_unit_cost >= 0", name="max_unit_cost_not_negative"
        ),
        CheckConstraint(
            "is_active or deactivated_at is not null",
            name="inactive_entry_records_when",
        ),
    )


class OosStatusHistory(UUIDPrimaryKeyMixin, OrganizationScopedMixin, TimestampMixin, Base):
    """Append-only record of a watched product's stock-state changes."""

    __tablename__ = "oos_status_history"

    oos_watchlist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("oos_watchlist.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True
    )

    previous_status: Mapped[OosStatus | None] = mapped_column(
        pg_enum(OosStatus, "oos_status"), nullable=True
    )
    new_status: Mapped[OosStatus] = mapped_column(pg_enum(OosStatus, "oos_status"), nullable=False)
    # The observation that caused the change, where one exists.
    vendor_inventory_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vendor_inventory_snapshots.id", ondelete="RESTRICT"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))

    watchlist_entry: Mapped[OosWatchlistEntry] = relationship(back_populates="status_history")
    product: Mapped[Product] = relationship()
    vendor: Mapped[Vendor | None] = relationship()
    snapshot: Mapped[VendorInventorySnapshot | None] = relationship()

    __table_args__ = (
        Index(
            "ix_oos_status_history_watchlist_changed_at",
            "oos_watchlist_id",
            "changed_at",
        ),
        # OOS-status search across history.
        Index(
            "ix_oos_status_history_organization_id_new_status",
            "organization_id",
            "new_status",
            "changed_at",
        ),
        Index("ix_oos_status_history_product_id_changed_at", "product_id", "changed_at"),
        CheckConstraint(
            "previous_status is null or previous_status <> new_status",
            name="history_records_an_actual_change",
        ),
    )
