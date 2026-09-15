"""The listing resolver against an in-memory catalog (CLAUDE.md §5.1, §5.2).

No database. The catalog is two dicts; the resolver is a pure function of the
listing and what the catalog answers, so every branch is pinned here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.models.enums import ExceptionReason, MatchMethod
from app.services.amazon_inventory import ParsedListing
from app.services.amazon_listings import Resolution, resolve_listing

PRODUCT_A = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
PRODUCT_B = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000002")
PRODUCT_C = uuid.UUID("cccccccc-0000-4000-8000-000000000003")

UPC_A = "012345678905"  # valid UPC-A
UPC_A_CANONICAL = "00012345678905"
EAN_B = "4006381333931"  # valid EAN-13
EAN_B_CANONICAL = "04006381333931"


class FakeCatalog:
    def __init__(
        self,
        by_sku: dict[str, list[uuid.UUID]] | None = None,
        by_gtin: dict[str, list[uuid.UUID]] | None = None,
    ) -> None:
        self.by_sku = by_sku or {}
        self.by_gtin = by_gtin or {}
        self.queries: list[tuple[str, str]] = []

    def products_by_amazon_sku(self, seller_sku: str) -> list[uuid.UUID]:
        self.queries.append(("amazon_sku", seller_sku))
        return list(self.by_sku.get(seller_sku, []))

    def products_by_gtin(self, canonical: str) -> list[uuid.UUID]:
        self.queries.append(("gtin", canonical))
        return list(self.by_gtin.get(canonical, []))


def listing(
    sku: str,
    *,
    product_id: str | None = None,
    id_type: int | None = None,
    name: str = "Blue Widget, 12 pack",
) -> ParsedListing:
    kinds = {1: "ASIN", 2: "ISBN", 3: "UPC", 4: "EAN"}
    return ParsedListing(
        seller_sku=sku,
        asin="B000TEST01",
        quantity=1,
        fulfillment_channel="DEFAULT",
        is_fbm=True,
        product_id=product_id,
        product_id_type=id_type,
        product_id_kind=kinds.get(id_type) if id_type is not None else None,
        item_name=name,
        status="Active",
        raw={"item-name": name},
    )


def rules(resolution: Resolution) -> list[tuple[str, str]]:
    return [(e.rule, e.outcome) for e in resolution.evaluations]


# --- branch a: priority 4 -----------------------------------------------------------


class TestPriority4:
    def test_an_amazon_sku_identifier_approves_the_listing(self) -> None:
        catalog = FakeCatalog(by_sku={"WIDGET-12": [PRODUCT_A]})

        resolution = resolve_listing(listing("WIDGET-12"), catalog)

        assert resolution.outcome == "APPROVED"
        assert resolution.product_id == PRODUCT_A
        assert resolution.method is MatchMethod.AMAZON_SKU_MAPPING
        assert resolution.exception_reason is None
        assert rules(resolution) == [("AMAZON_SKU_MAPPING", "matched"), ("UPC", "skipped")]

    def test_the_seller_sku_is_looked_up_trimmed_but_case_preserved(self) -> None:
        catalog = FakeCatalog(by_sku={"Widget-12": [PRODUCT_A]})

        resolution = resolve_listing(listing("  Widget-12 "), catalog)

        assert resolution.outcome == "APPROVED"
        assert catalog.queries[0] == ("amazon_sku", "Widget-12")

    def test_priority_4_wins_when_the_upc_agrees(self) -> None:
        catalog = FakeCatalog(
            by_sku={"WIDGET-12": [PRODUCT_A]}, by_gtin={UPC_A_CANONICAL: [PRODUCT_A]}
        )

        resolution = resolve_listing(listing("WIDGET-12", product_id=UPC_A, id_type=3), catalog)

        assert resolution.outcome == "APPROVED"
        assert resolution.method is MatchMethod.AMAZON_SKU_MAPPING
        # Both rules were evaluated and both are on record.
        assert rules(resolution) == [("AMAZON_SKU_MAPPING", "matched"), ("UPC", "matched")]

    def test_priority_4_wins_when_the_upc_has_no_hit(self) -> None:
        catalog = FakeCatalog(by_sku={"WIDGET-12": [PRODUCT_A]})

        resolution = resolve_listing(listing("WIDGET-12", product_id=UPC_A, id_type=3), catalog)

        assert resolution.outcome == "APPROVED"
        assert rules(resolution) == [("AMAZON_SKU_MAPPING", "matched"), ("UPC", "no_match")]

    def test_a_disagreeing_upc_blocks_the_approval(self) -> None:
        """Two rules, two products: nobody guesses (§5.2)."""
        catalog = FakeCatalog(
            by_sku={"WIDGET-12": [PRODUCT_A]}, by_gtin={UPC_A_CANONICAL: [PRODUCT_B]}
        )

        resolution = resolve_listing(listing("WIDGET-12", product_id=UPC_A, id_type=3), catalog)

        assert resolution.outcome == "UNMAPPED"
        assert resolution.product_id is None
        assert resolution.exception_reason is ExceptionReason.CONFLICTING_IDENTIFIER
        assert resolution.candidates == (PRODUCT_A, PRODUCT_B)

    def test_an_ambiguous_amazon_sku_stops_the_chain(self) -> None:
        """More than one product for the SKU: ambiguous, no fall-through (AC-7.4)."""
        catalog = FakeCatalog(
            by_sku={"WIDGET-12": [PRODUCT_A, PRODUCT_B]}, by_gtin={UPC_A_CANONICAL: [PRODUCT_C]}
        )

        resolution = resolve_listing(listing("WIDGET-12", product_id=UPC_A, id_type=3), catalog)

        assert resolution.outcome == "UNMAPPED"
        assert resolution.exception_reason is ExceptionReason.AMBIGUOUS_MATCH
        assert resolution.candidates == (PRODUCT_A, PRODUCT_B)
        assert rules(resolution) == [("AMAZON_SKU_MAPPING", "ambiguous"), ("UPC", "skipped")]
        # The UPC lookup never even ran.
        assert [q for q in catalog.queries if q[0] == "gtin"] == []


# --- branch b: priority 1 ----------------------------------------------------------------


class TestPriority1:
    def test_a_upc_hit_is_a_suggestion_not_an_approval(self) -> None:
        catalog = FakeCatalog(by_gtin={UPC_A_CANONICAL: [PRODUCT_A]})

        resolution = resolve_listing(listing("NEW-1", product_id=UPC_A, id_type=3), catalog)

        assert resolution.outcome == "PENDING"
        assert resolution.product_id == PRODUCT_A
        assert resolution.method is MatchMethod.UPC
        assert resolution.exception_reason is ExceptionReason.SUGGESTION_ONLY
        assert rules(resolution) == [("AMAZON_SKU_MAPPING", "no_match"), ("UPC", "matched")]

    def test_an_ean_is_normalised_to_gtin_14_before_lookup(self) -> None:
        catalog = FakeCatalog(by_gtin={EAN_B_CANONICAL: [PRODUCT_B]})

        resolution = resolve_listing(listing("NEW-1", product_id=EAN_B, id_type=4), catalog)

        assert resolution.outcome == "PENDING"
        assert resolution.product_id == PRODUCT_B
        assert catalog.queries[-1] == ("gtin", EAN_B_CANONICAL)

    def test_an_11_digit_upc_is_padded_before_lookup(self) -> None:
        catalog = FakeCatalog(by_gtin={UPC_A_CANONICAL: [PRODUCT_A]})

        resolution = resolve_listing(listing("NEW-1", product_id=UPC_A[1:], id_type=3), catalog)

        assert resolution.outcome == "PENDING"

    def test_a_bad_check_digit_never_reaches_the_catalog(self) -> None:
        catalog = FakeCatalog(by_gtin={"00012345678906": [PRODUCT_A]})

        resolution = resolve_listing(
            listing("NEW-1", product_id="012345678906", id_type=3), catalog
        )

        assert resolution.outcome == "UNMAPPED"
        assert resolution.exception_reason is ExceptionReason.NO_MATCH
        [_, upc] = resolution.evaluations
        assert upc.outcome == "skipped"
        assert upc.note is not None and "check digit" in upc.note
        assert [q for q in catalog.queries if q[0] == "gtin"] == []

    def test_an_ambiguous_upc_is_an_exception_not_a_pick(self) -> None:
        catalog = FakeCatalog(by_gtin={UPC_A_CANONICAL: [PRODUCT_A, PRODUCT_B]})

        resolution = resolve_listing(listing("NEW-1", product_id=UPC_A, id_type=3), catalog)

        assert resolution.outcome == "UNMAPPED"
        assert resolution.exception_reason is ExceptionReason.AMBIGUOUS_MATCH
        assert resolution.candidates == (PRODUCT_A, PRODUCT_B)

    @pytest.mark.parametrize("id_type", [1, 2, None])
    def test_an_asin_or_isbn_product_id_is_not_a_upc(self, id_type: int | None) -> None:
        catalog = FakeCatalog(by_gtin={UPC_A_CANONICAL: [PRODUCT_A]})

        resolution = resolve_listing(listing("NEW-1", product_id=UPC_A, id_type=id_type), catalog)

        assert resolution.outcome == "UNMAPPED"
        assert resolution.exception_reason is ExceptionReason.NO_MATCH
        assert [q for q in catalog.queries if q[0] == "gtin"] == []


# --- branch c: nothing fires -------------------------------------------------------------


class TestNoMatch:
    def test_no_rule_fires(self) -> None:
        resolution = resolve_listing(listing("NEW-1", product_id=UPC_A, id_type=3), FakeCatalog())

        assert resolution.outcome == "UNMAPPED"
        assert resolution.product_id is None
        assert resolution.method is None
        assert resolution.exception_reason is ExceptionReason.NO_MATCH
        assert resolution.candidates == ()
        assert rules(resolution) == [("AMAZON_SKU_MAPPING", "no_match"), ("UPC", "no_match")]

    def test_every_rule_tried_is_on_record_with_its_input(self) -> None:
        resolution = resolve_listing(listing("NEW-1", product_id=UPC_A, id_type=3), FakeCatalog())

        evaluations = resolution.evaluations_json(evaluated_at=datetime(2026, 9, 15, tzinfo=UTC))
        assert evaluations["source"] == "amazon_listings"
        assert [r["priority"] for r in evaluations["rules"]] == [4, 1]
        assert evaluations["rules"][0]["input"] == "NEW-1"
        assert evaluations["rules"][1]["input"] == UPC_A_CANONICAL


# --- what is never an input --------------------------------------------------------------


class TestItemNameIsNeverAnInput:
    def test_identical_names_with_different_upcs_resolve_independently(self) -> None:
        catalog = FakeCatalog(by_gtin={UPC_A_CANONICAL: [PRODUCT_A], EAN_B_CANONICAL: [PRODUCT_B]})
        same_name = "Blue Widget, 12 pack"

        first = resolve_listing(
            listing("SKU-1", product_id=UPC_A, id_type=3, name=same_name), catalog
        )
        second = resolve_listing(
            listing("SKU-2", product_id=EAN_B, id_type=4, name=same_name), catalog
        )

        assert first.product_id == PRODUCT_A
        assert second.product_id == PRODUCT_B

    def test_identical_names_without_identifiers_do_not_match_each_other(self) -> None:
        """A listing whose only signal is its name is unmatched — always."""
        catalog = FakeCatalog(by_gtin={UPC_A_CANONICAL: [PRODUCT_A]})
        same_name = "Blue Widget, 12 pack"

        with_upc = resolve_listing(
            listing("SKU-1", product_id=UPC_A, id_type=3, name=same_name), catalog
        )
        name_only = resolve_listing(listing("SKU-2", name=same_name), catalog)

        assert with_upc.product_id == PRODUCT_A
        assert name_only.outcome == "UNMAPPED"
        assert name_only.exception_reason is ExceptionReason.NO_MATCH
        assert name_only.candidates == ()

    def test_the_catalog_is_never_asked_about_a_name(self) -> None:
        catalog = FakeCatalog()

        resolve_listing(listing("SKU-1", name="Something very specific"), catalog)

        assert all(kind in ("amazon_sku", "gtin") for kind, _ in catalog.queries)
        assert all("Something" not in value for _, value in catalog.queries)


class TestDeterminism:
    def test_the_same_input_gives_the_same_resolution(self) -> None:
        catalog = FakeCatalog(by_gtin={UPC_A_CANONICAL: [PRODUCT_A]})
        parsed = listing("SKU-1", product_id=UPC_A, id_type=3)

        assert resolve_listing(parsed, catalog) == resolve_listing(parsed, catalog)
