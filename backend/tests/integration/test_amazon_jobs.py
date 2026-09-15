"""Stale-run recovery, organization resolution, the standalone listings run,
and the velocity report — against a real PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AmazonSyncRun, AuditEvent, MarketplaceListing
from app.models.enums import (
    ActorType,
    AmazonSyncJobType,
    IdentifierType,
    MappingStatus,
    MatchMethod,
    SyncStatus,
    TriggerType,
)
from app.services.amazon_listings import ListingsSyncAlreadyRunning, run_listings_sync
from app.services.amazon_runs import (
    AUDIT_ACTION_STALE,
    STALE_RUN_MESSAGE,
    AmazonOrganizationError,
    recover_stale_runs,
    resolve_amazon_organization,
)
from app.services.amazon_velocity import velocity_report
from tests.integration import factories
from tests.integration.test_amazon_listings_mapping import (
    MARKETPLACE,
    THREE_ROWS,
    UPC,
    UPC_CANONICAL,
    seed_catalog,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
TIMEOUT = timedelta(minutes=120)


# --- stale-run recovery -------------------------------------------------------------


def test_a_running_run_older_than_the_timeout_is_marked_failed(db_session: Session) -> None:
    organization = factories.make_organization(db_session)
    stale = factories.make_amazon_sync_run(
        db_session,
        organization,
        job_type=AmazonSyncJobType.ORDERS_REPORT,
        status=SyncStatus.RUNNING,
        started_at=NOW - timedelta(hours=3),
    )
    db_session.commit()

    recovered = recover_stale_runs(
        db_session, organization.id, AmazonSyncJobType.ORDERS_REPORT, now=NOW, timeout=TIMEOUT
    )

    assert recovered == [stale.id]
    db_session.refresh(stale)
    assert stale.status is SyncStatus.FAILED
    assert stale.completed_at == NOW
    assert stale.error_message == STALE_RUN_MESSAGE
    assert stale.error_details["exception"] == "StaleRun"
    assert stale.error_details["timeout_minutes"] == 120
    [event] = (
        db_session.execute(select(AuditEvent).where(AuditEvent.entity_id == stale.id))
        .scalars()
        .all()
    )
    assert event.action == AUDIT_ACTION_STALE
    assert event.actor_type is ActorType.SYSTEM
    assert event.before is not None and event.before["status"] == "RUNNING"
    assert event.after is not None and event.after["status"] == "FAILED"


def test_a_recent_running_run_is_left_alone(db_session: Session) -> None:
    organization = factories.make_organization(db_session)
    fresh = factories.make_amazon_sync_run(
        db_session,
        organization,
        job_type=AmazonSyncJobType.ORDERS_REPORT,
        status=SyncStatus.RUNNING,
        started_at=NOW - timedelta(minutes=30),
    )

    recovered = recover_stale_runs(
        db_session, organization.id, AmazonSyncJobType.ORDERS_REPORT, now=NOW, timeout=TIMEOUT
    )

    assert recovered == []
    assert fresh.status is SyncStatus.RUNNING


def test_recovery_is_scoped_to_the_job_type_and_the_organization(db_session: Session) -> None:
    organization = factories.make_organization(db_session)
    other = factories.make_organization(db_session)
    old_inventory = factories.make_amazon_sync_run(
        db_session,
        organization,
        job_type=AmazonSyncJobType.FBA_INVENTORY,
        status=SyncStatus.RUNNING,
        started_at=NOW - timedelta(days=1),
    )
    other_tenant = factories.make_amazon_sync_run(
        db_session,
        other,
        job_type=AmazonSyncJobType.ORDERS_REPORT,
        status=SyncStatus.RUNNING,
        started_at=NOW - timedelta(days=1),
    )
    db_session.commit()

    recovered = recover_stale_runs(
        db_session, organization.id, AmazonSyncJobType.ORDERS_REPORT, now=NOW, timeout=TIMEOUT
    )

    assert recovered == []
    assert old_inventory.status is SyncStatus.RUNNING
    assert other_tenant.status is SyncStatus.RUNNING


def test_recovery_frees_the_slot_for_a_new_run(db_session: Session) -> None:
    """The whole point: a dead process must not block the next scheduled run."""
    organization = factories.make_organization(db_session)
    factories.make_amazon_sync_run(
        db_session,
        organization,
        job_type=AmazonSyncJobType.LISTINGS_REPORT,
        status=SyncStatus.RUNNING,
        started_at=NOW - timedelta(hours=5),
    )
    db_session.commit()
    fetcher = _FakeFetcher(THREE_ROWS)

    with pytest.raises(ListingsSyncAlreadyRunning):
        run_listings_sync(
            db_session, organization.id, TriggerType.SCHEDULED, client=fetcher, now=lambda: NOW
        )

    recover_stale_runs(
        db_session, organization.id, AmazonSyncJobType.LISTINGS_REPORT, now=NOW, timeout=TIMEOUT
    )
    run = run_listings_sync(
        db_session, organization.id, TriggerType.SCHEDULED, client=fetcher, now=lambda: NOW
    )

    assert run.status is SyncStatus.COMPLETED
    statuses = sorted(
        r.status.value
        for r in db_session.execute(
            select(AmazonSyncRun).where(AmazonSyncRun.organization_id == organization.id)
        ).scalars()
    )
    assert statuses == ["COMPLETED", "FAILED"]


# --- organization resolution ----------------------------------------------------------


def test_a_single_active_organization_needs_no_slug(db_session: Session) -> None:
    # The shared test database may hold organizations from other tests that
    # committed; those are rolled back per test, so only this one is visible.
    organization = factories.make_organization(db_session)

    assert resolve_amazon_organization(db_session, None) == organization.id


def test_the_slug_selects_among_several(db_session: Session) -> None:
    first = factories.make_organization(db_session, slug="first-org")
    factories.make_organization(db_session, slug="second-org")

    assert resolve_amazon_organization(db_session, "first-org") == first.id
    with pytest.raises(AmazonOrganizationError, match="set AMAZON_ORGANIZATION_SLUG"):
        resolve_amazon_organization(db_session, None)
    with pytest.raises(AmazonOrganizationError, match="does not name"):
        resolve_amazon_organization(db_session, "nope")


# --- the standalone listings run --------------------------------------------------------


class _FakeFetcher:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.requests: list[str] = []

    def fetch_report(self, report_type: str, *args: Any, **kwargs: Any) -> bytes:
        self.requests.append(report_type)
        return self.content


def test_the_listings_run_maps_and_records_its_counts(db_session: Session) -> None:
    organization = factories.make_organization(db_session)
    seed_catalog(db_session, organization)
    fetcher = _FakeFetcher(THREE_ROWS)

    run = run_listings_sync(
        db_session, organization.id, TriggerType.MANUAL, client=fetcher, now=lambda: NOW
    )

    assert run.status is SyncStatus.COMPLETED
    assert run.job_type is AmazonSyncJobType.LISTINGS_REPORT
    assert (run.rows_seen, run.rows_created) == (3, 3)
    assert run.error_details["listings_mapping"]["approved"] == 1
    assert fetcher.requests == ["GET_MERCHANT_LISTINGS_ALL_DATA"]
    listings = (
        db_session.execute(
            select(MarketplaceListing).where(MarketplaceListing.organization_id == organization.id)
        )
        .scalars()
        .all()
    )
    assert {listing.mapping_status for listing in listings} == {
        MappingStatus.APPROVED,
        MappingStatus.PENDING,
        MappingStatus.UNMAPPED,
    }


# --- velocity -------------------------------------------------------------------------


def test_velocity_report_combines_orders_inventory_and_mapping(db_session: Session) -> None:
    organization = factories.make_organization(db_session)
    product = factories.make_product(db_session, organization, catalog_item_number="CIN-100")
    factories.make_identifier(
        db_session,
        organization,
        product,
        identifier_type=IdentifierType.UPC,
        raw_value=UPC,
        normalized_value=UPC_CANONICAL,
    )
    user = factories.make_user(db_session, organization)
    factories.make_marketplace_listing(
        db_session,
        organization,
        product,
        seller_sku="WIDGET-12",
        asin="B000TEST01",
        marketplace_id=MARKETPLACE,
        mapping_status=MappingStatus.APPROVED,
        mapping_method=MatchMethod.AMAZON_SKU_MAPPING,
        approved_by_user_id=user.id,
        approved_at=NOW,
    )
    run = factories.make_amazon_sync_run(
        db_session, organization, status=SyncStatus.COMPLETED, started_at=NOW, completed_at=NOW
    )
    # Orders: 3 units at 2 days, 4 at 10 days, 5 at 20 days, 6 at 40 days (outside), 9 cancelled.
    for days, qty, status in (
        (2, 3, "Shipped"),
        (10, 4, "Shipped"),
        (20, 5, "Shipped"),
        (40, 6, "Shipped"),
        (1, 9, "Cancelled"),
    ):
        factories.make_amazon_order_line(
            db_session,
            organization,
            run,
            seller_sku="WIDGET-12",
            purchase_date=NOW - timedelta(days=days),
            last_updated_at=NOW - timedelta(days=days),
            quantity_ordered=qty,
            order_status=status,
        )
    factories.make_amazon_order_line(
        db_session,
        organization,
        run,
        seller_sku="OTHER-1",
        purchase_date=NOW - timedelta(days=1),
        quantity_ordered=1,
    )
    # Two snapshots; the later one must win.
    factories.make_amazon_inventory_snapshot(
        db_session,
        organization,
        run,
        seller_sku="WIDGET-12",
        asin="B000TEST01",
        fulfillable=100,
        captured_at=NOW - timedelta(days=1),
    )
    later = factories.make_amazon_sync_run(
        db_session, organization, status=SyncStatus.COMPLETED, started_at=NOW, completed_at=NOW
    )
    factories.make_amazon_inventory_snapshot(
        db_session,
        organization,
        later,
        seller_sku="WIDGET-12",
        asin="B000TEST01",
        fulfillable=40,
        fbm_quantity=5,
        inbound_working=100,
        inbound_shipped=50,
        inbound_receiving=10,
        captured_at=NOW,
    )

    rows = velocity_report(db_session, organization.id, now=lambda: NOW)

    widget, other = rows  # sorted by 30-day units descending
    assert widget.seller_sku == "WIDGET-12"
    assert (widget.units_7, widget.units_14, widget.units_30) == (3, 7, 12)
    assert widget.avg_daily_14 == pytest.approx(0.5)
    assert (widget.fulfillable, widget.fbm_quantity, widget.inbound) == (40, 5, 160)
    assert widget.days_of_supply == pytest.approx(90.0)  # (40 + 5) / 0.5
    assert widget.catalog_item_number == "CIN-100"
    assert widget.upc == UPC
    assert widget.mapping_method is MatchMethod.AMAZON_SKU_MAPPING
    assert widget.asin == "B000TEST01"
    # A SKU with orders but no listing and no snapshot still appears.
    assert other.seller_sku == "OTHER-1"
    assert (other.units_7, other.fulfillable, other.days_of_supply) == (1, None, None)
    assert other.mapping_status is None


def test_velocity_top_and_product_level(db_session: Session) -> None:
    organization = factories.make_organization(db_session)
    product = factories.make_product(db_session, organization, catalog_item_number="CIN-200")
    user = factories.make_user(db_session, organization)
    for sku in ("PACK-1", "PACK-6"):
        factories.make_marketplace_listing(
            db_session,
            organization,
            product,
            seller_sku=sku,
            marketplace_id=MARKETPLACE,
            mapping_status=MappingStatus.APPROVED,
            mapping_method=MatchMethod.MANUAL_APPROVAL,
            approved_by_user_id=user.id,
            approved_at=NOW,
        )
    run = factories.make_amazon_sync_run(
        db_session, organization, status=SyncStatus.COMPLETED, started_at=NOW, completed_at=NOW
    )
    for sku, qty in (("PACK-1", 2), ("PACK-6", 3), ("LONER", 1)):
        factories.make_amazon_order_line(
            db_session,
            organization,
            run,
            seller_sku=sku,
            purchase_date=NOW - timedelta(days=1),
            quantity_ordered=qty,
        )

    by_sku = velocity_report(db_session, organization.id, now=lambda: NOW)
    by_product = velocity_report(db_session, organization.id, level="product", now=lambda: NOW)
    top_one = velocity_report(db_session, organization.id, level="product", top=1, now=lambda: NOW)

    assert [r.seller_sku for r in by_sku] == ["PACK-6", "PACK-1", "LONER"]
    assert [(r.seller_sku, r.units_7) for r in by_product] == [("PACK-1", 5), ("LONER", 1)]
    assert by_product[0].catalog_item_number == "CIN-200"
    assert [r.seller_sku for r in top_one] == ["PACK-1"]
