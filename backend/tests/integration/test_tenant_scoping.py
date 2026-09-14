"""Tenant scoping against a real database (ADR 0012).

Two organizations, one vendor each — with the *same* vendor code, which the
schema permits because ``vendors`` is unique on ``(organization_id, code)``.
That is precisely the shape of a cross-tenant leak: an unscoped lookup by code
returns both rows. These tests prove the helper returns, updates, and deletes
only the caller's tenant, including when the caller supplies the other
tenant's primary key.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Vendor
from app.repositories.scoping import ScopedRepository, TenantScope
from tests.integration import factories

pytestmark = pytest.mark.integration

SHARED_CODE = "SHARED"


@pytest.fixture
def two_tenants(db_session: Session) -> tuple[Vendor, Vendor]:
    """One vendor per organization, both using the same code."""
    organization_a = factories.make_organization(db_session, name="Tenant A")
    organization_b = factories.make_organization(db_session, name="Tenant B")
    vendor_a = factories.make_vendor(
        db_session, organization_a, code=SHARED_CODE, name="A's vendor"
    )
    vendor_b = factories.make_vendor(
        db_session, organization_b, code=SHARED_CODE, name="B's vendor"
    )
    return vendor_a, vendor_b


def test_the_leak_the_helper_prevents_is_real(
    db_session: Session, two_tenants: tuple[Vendor, Vendor]
) -> None:
    """Without scoping, a lookup by code sees both tenants' rows."""
    rows = db_session.execute(select(Vendor).where(Vendor.code == SHARED_CODE)).scalars().all()

    assert {row.organization_id for row in rows} == {
        two_tenants[0].organization_id,
        two_tenants[1].organization_id,
    }


def test_select_returns_only_the_callers_tenant(
    db_session: Session, two_tenants: tuple[Vendor, Vendor]
) -> None:
    vendor_a, vendor_b = two_tenants
    scope = TenantScope(vendor_a.organization_id)

    statement = scope.select(Vendor).where(Vendor.code == SHARED_CODE)
    rows = db_session.execute(statement).scalars().all()

    assert [row.id for row in rows] == [vendor_a.id]
    assert vendor_b.id not in {row.id for row in rows}


def test_lookup_by_another_tenants_primary_key_returns_nothing(
    db_session: Session, two_tenants: tuple[Vendor, Vendor]
) -> None:
    """A leaked or guessed UUID from tenant B is invisible to tenant A."""
    vendor_a, vendor_b = two_tenants
    scope = TenantScope(vendor_a.organization_id)

    statement = scope.select(Vendor).where(Vendor.id == vendor_b.id)
    found = db_session.execute(statement).scalar_one_or_none()

    assert found is None


def test_update_touches_only_the_callers_tenant(
    db_session: Session, two_tenants: tuple[Vendor, Vendor]
) -> None:
    vendor_a, vendor_b = two_tenants
    scope = TenantScope(vendor_a.organization_id)

    db_session.execute(
        scope.update(Vendor).where(Vendor.code == SHARED_CODE).values(name="renamed")
    )
    db_session.flush()
    db_session.expire_all()

    renamed_everywhere = db_session.execute(
        select(func.count()).select_from(Vendor).where(Vendor.name == "renamed")
    ).scalar_one()
    assert renamed_everywhere == 1
    assert db_session.get(Vendor, vendor_a.id).name == "renamed"  # type: ignore[union-attr]
    assert db_session.get(Vendor, vendor_b.id).name == "B's vendor"  # type: ignore[union-attr]


def test_delete_touches_only_the_callers_tenant(
    db_session: Session, two_tenants: tuple[Vendor, Vendor]
) -> None:
    vendor_a, vendor_b = two_tenants
    scope = TenantScope(vendor_a.organization_id)

    db_session.execute(scope.delete(Vendor).where(Vendor.code == SHARED_CODE))
    db_session.flush()
    db_session.expire_all()

    remaining_everywhere = db_session.execute(
        select(func.count()).select_from(Vendor).where(Vendor.code == SHARED_CODE)
    ).scalar_one()
    assert remaining_everywhere == 1
    assert db_session.get(Vendor, vendor_a.id) is None
    assert db_session.get(Vendor, vendor_b.id) is not None


def test_column_selection_and_aggregates_stay_scoped(
    db_session: Session, two_tenants: tuple[Vendor, Vendor]
) -> None:
    vendor_a, _ = two_tenants
    scope = TenantScope(vendor_a.organization_id)

    count = db_session.execute(scope.select(Vendor, func.count(Vendor.id))).scalar_one()
    names = db_session.execute(scope.select(Vendor, Vendor.name)).scalars().all()

    assert count == 1
    assert names == ["A's vendor"]


def test_a_scoped_repository_cannot_see_the_other_tenant(
    db_session: Session, two_tenants: tuple[Vendor, Vendor]
) -> None:
    """The shape every future repository takes."""
    vendor_a, vendor_b = two_tenants

    class VendorRepository(ScopedRepository):
        def by_code(self, code: str) -> Vendor | None:
            statement = self.select(Vendor).where(Vendor.code == code)
            return self.session.execute(statement).scalar_one_or_none()

        def all_ids(self) -> list[object]:
            return list(self.session.execute(self.select(Vendor, Vendor.id)).scalars().all())

    as_a = VendorRepository(db_session, vendor_a.organization_id)
    as_b = VendorRepository(db_session, vendor_b.organization_id)

    assert as_a.by_code(SHARED_CODE) is not None
    assert as_a.by_code(SHARED_CODE).id == vendor_a.id  # type: ignore[union-attr]
    assert as_b.by_code(SHARED_CODE).id == vendor_b.id  # type: ignore[union-attr]
    assert as_a.all_ids() == [vendor_a.id]
    assert as_b.all_ids() == [vendor_b.id]
