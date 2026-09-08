"""Transaction utilities roll back on failure (requirement 12).

The property being proved is the one ADR 0006 depends on: a change and its audit
row commit together or not at all. A rollback that leaves half the work behind
would make the audit trail a record of things that did not happen.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.transaction import savepoint, transaction
from app.models import Organization, Vendor
from tests.integration import factories

pytestmark = pytest.mark.integration


def _organization_count(session: Session) -> int:
    return session.execute(select(func.count()).select_from(Organization)).scalar_one()


class TestRollbackOnFailure:
    def test_an_exception_discards_every_write_in_the_block(self, db_session: Session) -> None:
        before = _organization_count(db_session)

        with pytest.raises(RuntimeError, match="deliberate"), transaction(db_session):
            factories.make_organization(db_session, slug="rolled-back-org")
            raise RuntimeError("deliberate failure")

        assert _organization_count(db_session) == before

    def test_the_exception_is_re_raised_not_swallowed(self, db_session: Session) -> None:
        """The helper controls the transaction; it does not handle errors."""

        class DomainError(Exception):
            pass

        with pytest.raises(DomainError), transaction(db_session):
            raise DomainError

    def test_a_constraint_violation_rolls_back_earlier_writes(self, db_session: Session) -> None:
        """The realistic case: the *second* write is what fails."""
        organization = factories.make_organization(db_session)
        db_session.commit()
        before = db_session.execute(select(func.count()).select_from(Vendor)).scalar_one()

        with pytest.raises(IntegrityError), transaction(db_session):
            factories.make_vendor(db_session, organization, code="DUPLICATE")
            factories.make_vendor(db_session, organization, code="DUPLICATE")

        after = db_session.execute(select(func.count()).select_from(Vendor)).scalar_one()
        assert after == before, "the first vendor survived a rolled-back transaction"

    def test_a_partial_multi_table_change_is_fully_discarded(self, db_session: Session) -> None:
        """A vendor and its audit row must not be able to disagree."""
        organization = factories.make_organization(db_session)
        db_session.commit()

        with pytest.raises(RuntimeError), transaction(db_session):
            factories.make_vendor(db_session, organization, code="PARTIAL")
            factories.make_product(db_session, organization, catalog_item_number="PART-1")
            raise RuntimeError("failure after two writes")

        assert (
            db_session.execute(select(Vendor).where(Vendor.code == "PARTIAL")).scalar_one_or_none()
            is None
        )


class TestCommitOnSuccess:
    def test_a_clean_block_commits(self, db_session: Session) -> None:
        before = _organization_count(db_session)

        with transaction(db_session):
            factories.make_organization(db_session, slug="committed-org")

        assert _organization_count(db_session) == before + 1

    def test_the_session_is_usable_after_a_rollback(self, db_session: Session) -> None:
        """A failed transaction must not poison the session for its successor."""
        with pytest.raises(RuntimeError), transaction(db_session):
            factories.make_organization(db_session, slug="doomed")
            raise RuntimeError("boom")

        with transaction(db_session):
            survivor = factories.make_organization(db_session, slug="survivor")

        assert db_session.get(Organization, survivor.id) is not None


class TestSavepoints:
    def test_an_inner_failure_leaves_the_outer_transaction_intact(
        self, db_session: Session
    ) -> None:
        """One bad row in an import batch should not discard the batch."""
        organization = factories.make_organization(db_session)
        db_session.commit()

        with transaction(db_session):
            factories.make_vendor(db_session, organization, code="KEEPME")

            with pytest.raises(IntegrityError), savepoint(db_session):
                factories.make_vendor(db_session, organization, code="KEEPME")

        kept = db_session.execute(select(Vendor).where(Vendor.code == "KEEPME")).scalars().all()
        assert len(kept) == 1
