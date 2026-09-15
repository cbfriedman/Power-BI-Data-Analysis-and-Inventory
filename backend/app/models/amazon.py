"""Amazon SP-API ingestion: run bookkeeping, order lines, inventory snapshots.

Tables for the read-only ingestion admitted by ADR 0011. Listings land in
the existing ``marketplace_listings`` (ADR 0010); these three tables hold
what has no home yet — the run record, the order lines that sales velocity
is computed from, and point-in-time FBA/FBM inventory positions.

Nothing here contains an SP-API field name. The anti-corruption layer in
``app/integrations/amazon`` maps Amazon's shapes into these columns; ``raw``
retains the subset of fields the ingestion chose to keep, never the whole
record, and **never a buyer or shipping field** (ADR 0011: no PII).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AmazonSyncJobType, SyncStatus, TriggerType
from app.models.mixins import (
    OrganizationScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    pg_enum,
)

if TYPE_CHECKING:
    from app.models.identity import User


class AmazonSyncRun(UUIDPrimaryKeyMixin, OrganizationScopedMixin, TimestampMixin, Base):
    """One Amazon ingestion execution — one job type, one marketplace, one outcome.

    A partial unique index allows a single ``RUNNING`` row per organization
    and job type, which is what stops a scheduler tick from starting a second
    orders pull while the first is still polling its report. A check
    constraint keeps ``completed_at`` empty while the run is ``RUNNING``, so
    the two cannot disagree about whether the run is over.
    """

    __tablename__ = "amazon_sync_runs"

    job_type: Mapped[AmazonSyncJobType] = mapped_column(
        pg_enum(AmazonSyncJobType, "amazon_sync_job_type"), nullable=False
    )
    status: Mapped[SyncStatus] = mapped_column(
        pg_enum(SyncStatus, "sync_status"),
        nullable=False,
        server_default=SyncStatus.PENDING.value,
    )
    trigger_type: Mapped[TriggerType] = mapped_column(
        pg_enum(TriggerType, "trigger_type"),
        nullable=False,
        server_default=TriggerType.MANUAL.value,
    )

    # The data window the run asked Amazon for. Null for reads that have no
    # window, such as an inventory summary.
    window_start: Mapped[datetime | None] = mapped_column(nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(nullable=True)
    marketplace_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # Amazon's id for the report this run requested, when it requested one.
    report_id: Mapped[str | None] = mapped_column(nullable=True)

    rows_seen: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rows_created: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rows_updated: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rows_unchanged: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rows_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    error_message: Mapped[str | None] = mapped_column(nullable=True)
    error_details: Mapped[dict[str, Any]] = mapped_column(
        nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )

    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # RESTRICT, as with audit attribution: a user who has triggered a run is
    # deactivated, never deleted. Null for scheduled runs.
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    # Correlation id of the request that triggered the run, if any.
    request_id: Mapped[str | None] = mapped_column(nullable=True)

    triggered_by: Mapped[User | None] = relationship()

    __table_args__ = (
        Index(
            "uq_amazon_sync_runs_running_job",
            "organization_id",
            "job_type",
            unique=True,
            postgresql_where=text("status = 'RUNNING'"),
        ),
        Index(
            "ix_amazon_sync_runs_organization_id_job_type_status",
            "organization_id",
            "job_type",
            "status",
            "started_at",
        ),
        CheckConstraint(
            "rows_seen >= 0 and rows_created >= 0 and rows_updated >= 0"
            " and rows_unchanged >= 0 and rows_failed >= 0",
            name="counts_not_negative",
        ),
        CheckConstraint(
            "status <> 'RUNNING' or completed_at is null",
            name="running_has_no_completed_at",
        ),
        CheckConstraint(
            "completed_at is null or started_at is not null",
            name="completed_requires_started",
        ),
        CheckConstraint(
            "completed_at is null or started_at is null or completed_at >= started_at",
            name="completed_after_started",
        ),
        CheckConstraint(
            "window_start is null or window_end is null or window_end >= window_start",
            name="window_end_after_start",
        ),
    )


class AmazonOrderLine(UUIDPrimaryKeyMixin, OrganizationScopedMixin, TimestampMixin, Base):
    """One (order, seller SKU) line, as needed for 7/14/30-day sales velocity.

    **Why the grain is (order, SKU) rather than order item.** The
    all-orders flat-file report — the cheapest way to pull a 30-day window —
    carries no order-item identifier, and an order can list the same SKU on
    more than one line (a promotion split, a partial cancellation). The
    ingestion therefore aggregates a report's lines per
    ``(amazon_order_id, seller_sku)`` before the upsert, and this table's
    uniqueness is on exactly that pair. ``quantity_ordered`` is the sum.

    ``order_status`` and ``item_status`` are stored as Amazon sends them
    (``Shipped``, ``Pending``, ``Canceled`` …) rather than as an enum, because
    the vocabulary is Amazon's to change and a velocity query filters on it
    explicitly. ``raw`` keeps only the columns the ingestion chose to retain;
    it never holds a buyer name, address, phone or email — there are no
    ``ship-*`` or ``buyer-*`` fields anywhere in this table, by design.

    ``first_seen_sync_run_id`` / ``last_seen_sync_run_id`` give provenance
    without copying the run's window onto every line.
    """

    __tablename__ = "amazon_order_lines"

    amazon_order_id: Mapped[str] = mapped_column(String(32), nullable=False)
    seller_sku: Mapped[str] = mapped_column(nullable=False)
    asin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    quantity_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    purchase_date: Mapped[datetime] = mapped_column(nullable=False)
    last_updated_at: Mapped[datetime] = mapped_column(nullable=False)
    order_status: Mapped[str] = mapped_column(String(32), nullable=False)
    item_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fulfillment_channel: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sales_channel: Mapped[str | None] = mapped_column(nullable=True)
    marketplace_id: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    item_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    first_seen_sync_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("amazon_sync_runs.id", ondelete="RESTRICT"), nullable=False
    )
    last_seen_sync_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("amazon_sync_runs.id", ondelete="RESTRICT"), nullable=False
    )
    raw: Mapped[dict[str, Any]] = mapped_column(
        nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )

    first_seen_sync_run: Mapped[AmazonSyncRun] = relationship(foreign_keys=[first_seen_sync_run_id])
    last_seen_sync_run: Mapped[AmazonSyncRun] = relationship(foreign_keys=[last_seen_sync_run_id])

    __table_args__ = (
        Index(
            "uq_amazon_order_lines_order_sku",
            "organization_id",
            "amazon_order_id",
            "seller_sku",
            unique=True,
        ),
        Index(
            "ix_amazon_order_lines_sku_purchase_date",
            "organization_id",
            "seller_sku",
            "purchase_date",
        ),
        Index("ix_amazon_order_lines_purchase_date", "organization_id", "purchase_date"),
        Index("ix_amazon_order_lines_first_seen_sync_run_id", "first_seen_sync_run_id"),
        Index("ix_amazon_order_lines_last_seen_sync_run_id", "last_seen_sync_run_id"),
        CheckConstraint("quantity_ordered >= 0", name="quantity_not_negative"),
        CheckConstraint("item_price is null or item_price >= 0", name="item_price_not_negative"),
        CheckConstraint("length(trim(amazon_order_id)) > 0", name="order_id_not_blank"),
        CheckConstraint("length(trim(seller_sku)) > 0", name="seller_sku_not_blank"),
        CheckConstraint(
            "(item_price is null) or (currency is not null)", name="price_requires_currency"
        ),
    )


class AmazonInventorySnapshot(UUIDPrimaryKeyMixin, OrganizationScopedMixin, TimestampMixin, Base):
    """One seller SKU's inventory position as observed by one ingestion run.

    Append-only history keyed on ``(sync_run_id, seller_sku)``: every run
    writes a fresh row per SKU and never updates an earlier one, so "what did
    we think was inbound last Tuesday" is a query, not a guess. The FBA
    quantities are ``NOT NULL`` — the ingestion converts an omitted Amazon
    field to ``0`` explicitly, and ``raw`` keeps what Amazon actually sent so
    the two can be told apart. ``fbm_quantity`` is nullable because
    merchant-fulfilled stock comes from a different source and may not have
    been fetched in the same run.
    """

    __tablename__ = "amazon_inventory_snapshots"

    seller_sku: Mapped[str] = mapped_column(nullable=False)
    asin: Mapped[str] = mapped_column(String(16), nullable=False)
    fnsku: Mapped[str | None] = mapped_column(String(16), nullable=True)
    condition: Mapped[str | None] = mapped_column(String(32), nullable=True)

    fulfillable: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    inbound_working: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    inbound_shipped: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    inbound_receiving: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    reserved_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    unfulfillable_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    researching_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    fbm_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # When Amazon says it last changed the position; null if not reported.
    amazon_last_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # When we read it.
    captured_at: Mapped[datetime] = mapped_column(nullable=False)

    sync_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("amazon_sync_runs.id", ondelete="RESTRICT"), nullable=False
    )
    raw: Mapped[dict[str, Any]] = mapped_column(
        nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )

    sync_run: Mapped[AmazonSyncRun] = relationship()

    __table_args__ = (
        Index(
            "uq_amazon_inventory_snapshots_run_sku",
            "sync_run_id",
            "seller_sku",
            unique=True,
        ),
        Index(
            "ix_amazon_inventory_snapshots_sku_captured_at",
            "organization_id",
            "seller_sku",
            text("captured_at DESC"),
        ),
        CheckConstraint(
            "fulfillable >= 0 and inbound_working >= 0 and inbound_shipped >= 0"
            " and inbound_receiving >= 0 and reserved_total >= 0"
            " and unfulfillable_total >= 0 and researching_total >= 0",
            name="quantities_not_negative",
        ),
        CheckConstraint(
            "fbm_quantity is null or fbm_quantity >= 0", name="fbm_quantity_not_negative"
        ),
        CheckConstraint("length(trim(seller_sku)) > 0", name="seller_sku_not_blank"),
    )
