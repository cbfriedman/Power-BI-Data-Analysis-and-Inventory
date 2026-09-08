"""Builders for database rows.

Deliberately plain functions rather than a factory framework: each one creates
the minimum valid row and flushes it, so a test reads as a short setup followed
by the single thing it is actually asserting.

Defaults are made unique with a counter, so a test that creates two of something
does not trip a unique constraint it was not testing.
"""

from __future__ import annotations

import hashlib
import itertools
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    AvailabilityEvent,
    ImportFile,
    ImportJob,
    ImportJobRow,
    MarketplaceListing,
    OosStatusHistory,
    OosWatchlistEntry,
    Organization,
    Product,
    ProductIdentifier,
    ProductMappingException,
    Role,
    User,
    Vendor,
    VendorImportProfile,
    VendorInventorySnapshot,
    VendorProduct,
)
from app.models.enums import (
    AvailabilityEventType,
    AvailabilityStatus,
    ExceptionReason,
    FileFormat,
    IdentifierType,
    ImportJobStatus,
    Marketplace,
    SourceSystem,
)

_counter = itertools.count(1)


def unique(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def fake_sha256(seed: str | None = None) -> str:
    return hashlib.sha256((seed or unique("blob")).encode()).hexdigest()


def make_organization(session: Session, *, slug: str | None = None, **kwargs: Any) -> Organization:
    organization = Organization(
        name=kwargs.pop("name", "Acme Distribution"),
        slug=slug or unique("acme"),
        **kwargs,
    )
    session.add(organization)
    session.flush()
    return organization


def make_user(session: Session, organization: Organization, **kwargs: Any) -> User:
    user = User(
        organization_id=organization.id,
        email=kwargs.pop("email", f"{unique('buyer')}@example.test"),
        display_name=kwargs.pop("display_name", "Test Buyer"),
        **kwargs,
    )
    session.add(user)
    session.flush()
    return user


def make_role(session: Session, organization: Organization, **kwargs: Any) -> Role:
    role = Role(
        organization_id=organization.id,
        code=kwargs.pop("code", unique("ROLE").upper()),
        name=kwargs.pop("name", "Reviewer"),
        **kwargs,
    )
    session.add(role)
    session.flush()
    return role


def make_vendor(session: Session, organization: Organization, **kwargs: Any) -> Vendor:
    vendor = Vendor(
        organization_id=organization.id,
        code=kwargs.pop("code", unique("VEND").upper()),
        name=kwargs.pop("name", "Test Vendor"),
        **kwargs,
    )
    session.add(vendor)
    session.flush()
    return vendor


def make_product(session: Session, organization: Organization, **kwargs: Any) -> Product:
    product = Product(
        organization_id=organization.id,
        catalog_item_number=kwargs.pop("catalog_item_number", unique("CIN")),
        name=kwargs.pop("name", "Blue Widget, 12 pack"),
        **kwargs,
    )
    session.add(product)
    session.flush()
    return product


def make_identifier(
    session: Session,
    organization: Organization,
    product: Product,
    **kwargs: Any,
) -> ProductIdentifier:
    value = kwargs.pop("normalized_value", unique("00012345678905"))
    identifier = ProductIdentifier(
        organization_id=organization.id,
        product_id=product.id,
        identifier_type=kwargs.pop("identifier_type", IdentifierType.UPC),
        raw_value=kwargs.pop("raw_value", value),
        normalized_value=value,
        source_system=kwargs.pop("source_system", SourceSystem.NINEYARD),
        **kwargs,
    )
    session.add(identifier)
    session.flush()
    return identifier


def make_marketplace_listing(
    session: Session,
    organization: Organization,
    product: Product,
    **kwargs: Any,
) -> MarketplaceListing:
    listing = MarketplaceListing(
        organization_id=organization.id,
        product_id=product.id,
        marketplace=kwargs.pop("marketplace", Marketplace.AMAZON),
        marketplace_id=kwargs.pop("marketplace_id", "ATVPDKIKX0DER"),
        seller_sku=kwargs.pop("seller_sku", unique("SKU")),
        **kwargs,
    )
    session.add(listing)
    session.flush()
    return listing


def make_vendor_product(
    session: Session,
    organization: Organization,
    vendor: Vendor,
    **kwargs: Any,
) -> VendorProduct:
    sku = kwargs.pop("vendor_sku", unique("VSKU"))
    vendor_product = VendorProduct(
        organization_id=organization.id,
        vendor_id=vendor.id,
        vendor_sku=sku,
        normalized_vendor_sku=kwargs.pop("normalized_vendor_sku", sku.lower()),
        **kwargs,
    )
    session.add(vendor_product)
    session.flush()
    return vendor_product


def make_import_profile(
    session: Session,
    organization: Organization,
    vendor: Vendor,
    **kwargs: Any,
) -> VendorImportProfile:
    profile = VendorImportProfile(
        organization_id=organization.id,
        vendor_id=vendor.id,
        name=kwargs.pop("name", unique("inventory")),
        file_format=kwargs.pop("file_format", FileFormat.CSV),
        **kwargs,
    )
    session.add(profile)
    session.flush()
    return profile


def make_import_file(
    session: Session,
    organization: Organization,
    vendor: Vendor,
    **kwargs: Any,
) -> ImportFile:
    import_file = ImportFile(
        organization_id=organization.id,
        vendor_id=vendor.id,
        original_filename=kwargs.pop("original_filename", "inventory.csv"),
        storage_uri=kwargs.pop("storage_uri", f"file:///storage/raw/{unique('f')}.csv"),
        sha256=kwargs.pop("sha256", fake_sha256()),
        size_bytes=kwargs.pop("size_bytes", 2048),
        **kwargs,
    )
    session.add(import_file)
    session.flush()
    return import_file


def make_import_job(
    session: Session,
    organization: Organization,
    vendor: Vendor,
    import_file: ImportFile,
    **kwargs: Any,
) -> ImportJob:
    job = ImportJob(
        organization_id=organization.id,
        vendor_id=vendor.id,
        import_file_id=import_file.id,
        status=kwargs.pop("status", ImportJobStatus.PENDING),
        **kwargs,
    )
    session.add(job)
    session.flush()
    return job


def make_import_job_row(
    session: Session,
    organization: Organization,
    job: ImportJob,
    **kwargs: Any,
) -> ImportJobRow:
    row = ImportJobRow(
        organization_id=organization.id,
        import_job_id=job.id,
        row_number=kwargs.pop("row_number", next(_counter)),
        raw_data=kwargs.pop("raw_data", {"sku": "ABC", "qty": "5"}),
        **kwargs,
    )
    session.add(row)
    session.flush()
    return row


def make_snapshot(
    session: Session,
    organization: Organization,
    vendor: Vendor,
    vendor_product: VendorProduct,
    job: ImportJob,
    **kwargs: Any,
) -> VendorInventorySnapshot:
    snapshot = VendorInventorySnapshot(
        organization_id=organization.id,
        vendor_id=vendor.id,
        vendor_product_id=vendor_product.id,
        import_job_id=job.id,
        availability_status=kwargs.pop("availability_status", AvailabilityStatus.AVAILABLE),
        quantity_available=kwargs.pop("quantity_available", Decimal("10")),
        effective_at=kwargs.pop("effective_at", datetime.now(UTC)),
        **kwargs,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def make_availability_event(
    session: Session,
    organization: Organization,
    vendor: Vendor,
    vendor_product: VendorProduct,
    current_snapshot: VendorInventorySnapshot,
    **kwargs: Any,
) -> AvailabilityEvent:
    event = AvailabilityEvent(
        organization_id=organization.id,
        vendor_id=vendor.id,
        vendor_product_id=vendor_product.id,
        current_snapshot_id=current_snapshot.id,
        event_type=kwargs.pop("event_type", AvailabilityEventType.BECAME_AVAILABLE),
        previous_status=kwargs.pop("previous_status", AvailabilityStatus.OUT_OF_STOCK),
        new_status=kwargs.pop("new_status", AvailabilityStatus.AVAILABLE),
        **kwargs,
    )
    session.add(event)
    session.flush()
    return event


def make_watchlist_entry(
    session: Session,
    organization: Organization,
    product: Product,
    **kwargs: Any,
) -> OosWatchlistEntry:
    entry = OosWatchlistEntry(
        organization_id=organization.id,
        product_id=product.id,
        **kwargs,
    )
    session.add(entry)
    session.flush()
    return entry


def make_oos_status_history(
    session: Session,
    organization: Organization,
    entry: OosWatchlistEntry,
    product: Product,
    **kwargs: Any,
) -> OosStatusHistory:
    history = OosStatusHistory(
        organization_id=organization.id,
        oos_watchlist_id=entry.id,
        product_id=product.id,
        new_status=kwargs.pop("new_status", "OUT_OF_STOCK"),
        **kwargs,
    )
    session.add(history)
    session.flush()
    return history


def make_mapping_exception(
    session: Session,
    organization: Organization,
    vendor: Vendor,
    **kwargs: Any,
) -> ProductMappingException:
    exception = ProductMappingException(
        organization_id=organization.id,
        vendor_id=vendor.id,
        reason=kwargs.pop("reason", ExceptionReason.NO_MATCH),
        **kwargs,
    )
    session.add(exception)
    session.flush()
    return exception
