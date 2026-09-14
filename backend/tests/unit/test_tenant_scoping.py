"""Tenant scoping helper (ADR 0012).

These tests never touch a database. They introspect the ORM registry to find
every organization-owned model and prove, from the compiled SQL, that the
helper puts ``organization_id = :id`` on a select, an update, and a delete for
each one. The set of scoped models is cross-checked against the schema so a
new table cannot appear without being covered.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
from sqlalchemy.sql import ClauseElement

import app.models  # noqa: F401 — registers every mapped class on Base.registry
from app.db.base import Base
from app.models import Organization, Vendor
from app.models.mixins import OrganizationScopedMixin
from app.repositories.scoping import (
    ScopedRepository,
    TenantScope,
    TenantScopingError,
    require_scoped_model,
)

ORGANIZATION_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")


def scoped_models() -> list[type[Base]]:
    found: list[type[Base]] = []
    for mapper in Base.registry.mappers:
        model = mapper.class_
        if issubclass(model, Base) and issubclass(model, OrganizationScopedMixin):
            found.append(model)
    return sorted(found, key=lambda cls: str(cls.__tablename__))


def compiled(statement: ClauseElement) -> str:
    """Render with literal binds so the tenant id is visible in the SQL."""
    # Dialect constructors carry no type hints upstream.
    dialect = PGDialect_psycopg()  # type: ignore[no-untyped-call]
    return str(statement.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


def expected_filter(model: type[Base]) -> str:
    return f"{model.__tablename__}.organization_id = '{ORGANIZATION_ID}'"


# --- Coverage of the registry ------------------------------------------------


def test_every_table_except_organizations_is_scoped() -> None:
    """The one unscoped table is the tenant itself."""
    all_tables = {table.name for table in Base.metadata.sorted_tables}
    scoped_tables = {model.__tablename__ for model in scoped_models()}

    assert all_tables - scoped_tables == {"organizations"}
    assert len(scoped_tables) == len(all_tables) - 1


# --- One assertion per model, per statement kind ---------------------------


@pytest.mark.parametrize("model", scoped_models(), ids=lambda m: m.__tablename__)
def test_select_is_scoped(model: type[Base]) -> None:
    sql = compiled(TenantScope(ORGANIZATION_ID).select(model))

    assert "WHERE" in sql
    assert expected_filter(model) in sql


@pytest.mark.parametrize("model", scoped_models(), ids=lambda m: m.__tablename__)
def test_update_is_scoped(model: type[Base]) -> None:
    sql = compiled(
        TenantScope(ORGANIZATION_ID).update(model).values(organization_id=ORGANIZATION_ID)
    )

    assert sql.startswith(f"UPDATE {model.__tablename__}")
    assert expected_filter(model) in sql


@pytest.mark.parametrize("model", scoped_models(), ids=lambda m: m.__tablename__)
def test_delete_is_scoped(model: type[Base]) -> None:
    sql = compiled(TenantScope(ORGANIZATION_ID).delete(model))

    assert sql.startswith(f"DELETE FROM {model.__tablename__}")
    assert expected_filter(model) in sql


# --- Behaviour of the helper itself -----------------------------------------


def test_selecting_columns_keeps_the_filter_on_the_model() -> None:
    sql = compiled(TenantScope(ORGANIZATION_ID).select(Vendor, Vendor.code, Vendor.name))

    assert sql.startswith("SELECT vendors.code, vendors.name")
    assert expected_filter(Vendor) in sql


def test_apply_adds_the_filter_to_an_existing_statement() -> None:
    """A caller's own predicates are kept; the tenant filter is ANDed on."""
    statement = select(Vendor).where(Vendor.code == "ACME")

    sql = compiled(TenantScope(ORGANIZATION_ID).apply(statement, Vendor))

    assert "vendors.code = 'ACME'" in sql
    assert expected_filter(Vendor) in sql
    assert " AND " in sql


def test_the_scope_is_immutable() -> None:
    scope = TenantScope(ORGANIZATION_ID)

    with pytest.raises(AttributeError):
        scope.organization_id = uuid.uuid4()  # type: ignore[misc]


def test_organizations_cannot_be_scoped() -> None:
    """The tenant table is not tenant-owned; asking for it is a bug."""
    with pytest.raises(TenantScopingError, match="not organization-scoped"):
        TenantScope(ORGANIZATION_ID).select(Organization)


def test_a_non_model_cannot_be_scoped() -> None:
    with pytest.raises(TenantScopingError):
        require_scoped_model(dict)


@pytest.mark.parametrize("bad", [None, str(ORGANIZATION_ID), 42])
def test_organization_id_must_be_a_uuid(bad: object) -> None:
    """``None`` would compile to ``IS NULL`` and match nothing, silently."""
    with pytest.raises(TenantScopingError, match=r"must be a uuid.UUID"):
        TenantScope(bad)  # type: ignore[arg-type]


def test_scoped_repository_builds_through_its_scope() -> None:
    class VendorRepository(ScopedRepository):
        pass

    repository = VendorRepository(session=None, organization_id=ORGANIZATION_ID)  # type: ignore[arg-type]

    assert repository.scope == TenantScope(ORGANIZATION_ID)
    assert expected_filter(Vendor) in compiled(repository.select(Vendor))
    assert expected_filter(Vendor) in compiled(repository.update(Vendor).values(name="x"))
    assert expected_filter(Vendor) in compiled(repository.delete(Vendor))
