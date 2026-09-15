"""Parsing the all-orders flat-file report (ADR 0011).

The fixture is shaped after Amazon's ``GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_
UPDATE_GENERAL`` output — its real column set, including the ``ship-*``
columns that must never be retained. It is a fixture, not an observation:
the live report has not been pulled yet (B8).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.services.amazon_orders import (
    MAX_WINDOW_DAYS,
    REQUIRED_COLUMNS,
    ParsedOrderLine,
    ReportFormatError,
    decode_report,
    parse_orders_report,
    trailing_window,
    validate_window,
)

HEADER = (
    "amazon-order-id\tmerchant-order-id\tpurchase-date\tlast-updated-date\torder-status"
    "\tfulfillment-channel\tsales-channel\torder-channel\turl\tship-service-level"
    "\tproduct-name\tsku\tasin\titem-status\tquantity\tcurrency\titem-price\titem-tax"
    "\tshipping-price\tshipping-tax\tgift-wrap-price\tgift-wrap-tax"
    "\titem-promotion-discount\tship-promotion-discount\tship-city\tship-state"
    "\tship-postal-code\tship-country\tpromotion-ids\tis-business-order"
    "\tpurchase-order-number\tprice-designation"
)


def row(
    order: str,
    sku: str,
    *,
    purchase: str = "2026-09-10T14:03:22+00:00",
    updated: str = "2026-09-10T15:00:00+00:00",
    status: str = "Shipped",
    channel: str = "Amazon",
    sales: str = "Amazon.com",
    name: str = "Blue Widget, 12 pack",
    asin: str = "B000TEST01",
    item_status: str = "Shipped",
    qty: str = "1",
    currency: str = "USD",
    price: str = "19.99",
    city: str = "SPRINGFIELD",
) -> str:
    return "\t".join(
        [
            order, "", purchase, updated, status, channel, sales, "", "", "Standard",
            name, sku, asin, item_status, qty, currency, price, "1.20",
            "0.00", "0.00", "", "", "0.00", "0.00", city, "IL",
            "62704", "US", "", "false", "", "",
        ]
    )  # fmt: skip


FIXTURE_ROWS = [
    # a normal FBA line
    row("111-1000000-0000001", "WIDGET-12"),
    # an FBM line
    row("111-1000000-0000002", "GADGET-1", channel="Merchant", asin="B000TEST02"),
    # a Cancelled line
    row(
        "111-1000000-0000003",
        "WIDGET-12",
        status="Cancelled",
        item_status="Cancelled",
        qty="0",
        price="",
        currency="",
    ),
    # a Pending line (no price yet)
    row("111-1000000-0000004", "WIDGET-12", status="Pending", item_status="Unshipped", price=""),
    # two lines for the same order and SKU — the second is the later update
    row("111-1000000-0000005", "WIDGET-12", qty="2", updated="2026-09-11T08:00:00+00:00"),
    row(
        "111-1000000-0000005",
        "WIDGET-12",
        qty="3",
        updated="2026-09-12T08:00:00+00:00",
        status="Shipped",
        item_status="Shipped",
    ),
    # a line with a missing asin
    row("111-1000000-0000006", "NOASIN-1", asin=""),
    # a latin-1 product name
    row("111-1000000-0000007", "CAFE-1", name="Café Crème Set, 6 pièces", asin="B000CAFE01"),
    # a line with quantity 0 that is not cancelled
    row("111-1000000-0000008", "ZERO-1", qty="0", price="", currency=""),
]

FIXTURE_TEXT = HEADER + "\n" + "\n".join(FIXTURE_ROWS) + "\n"
FIXTURE_LATIN1 = FIXTURE_TEXT.encode("latin-1")  # every character is Latin-1 encodable
FIXTURE_UTF8 = FIXTURE_TEXT.encode("utf-8")


def by_key(lines: list[ParsedOrderLine]) -> dict[tuple[str, str], ParsedOrderLine]:
    return {(line.amazon_order_id, line.seller_sku): line for line in lines}


class TestDecoding:
    def test_utf8_is_preferred(self) -> None:
        text, encoding = decode_report(FIXTURE_UTF8)

        assert encoding == "utf-8"
        assert "Café Crème Set, 6 pièces" in text

    def test_utf8_bom_is_stripped(self) -> None:
        text, _ = decode_report(b"\xef\xbb\xbf" + FIXTURE_UTF8)

        assert text.startswith("amazon-order-id")

    def test_latin1_fallback(self) -> None:
        """Latin-1 bytes for accented characters are not valid UTF-8."""
        text, encoding = decode_report("Café Crème".encode("latin-1"))

        assert encoding == "latin-1"
        assert text == "Café Crème"


class TestFixtureParsing:
    @pytest.fixture(params=["utf-8", "latin-1"])
    def content(self, request: pytest.FixtureRequest) -> bytes:
        return FIXTURE_UTF8 if request.param == "utf-8" else FIXTURE_LATIN1

    def test_every_row_is_seen_and_none_fails(self, content: bytes) -> None:
        result = parse_orders_report(content)

        assert result.rows_seen == 9
        assert result.rows_failed == 0
        assert result.errors == []

    def test_lines_are_aggregated_per_order_and_sku(self, content: bytes) -> None:
        result = parse_orders_report(content)

        assert len(result.lines) == 8  # 9 rows, one pair repeated

    def test_a_normal_fba_line(self, content: bytes) -> None:
        line = by_key(parse_orders_report(content).lines)[("111-1000000-0000001", "WIDGET-12")]

        assert line.asin == "B000TEST01"
        assert line.quantity_ordered == 1
        assert line.purchase_date == datetime(2026, 9, 10, 14, 3, 22, tzinfo=UTC)
        assert line.last_updated_at == datetime(2026, 9, 10, 15, 0, tzinfo=UTC)
        assert line.order_status == "Shipped"
        assert line.item_status == "Shipped"
        assert line.fulfillment_channel == "Amazon"
        assert line.sales_channel == "Amazon.com"
        assert line.currency == "USD"
        assert line.item_price == Decimal("19.99")

    def test_an_fbm_line(self, content: bytes) -> None:
        line = by_key(parse_orders_report(content).lines)[("111-1000000-0000002", "GADGET-1")]

        assert line.fulfillment_channel == "Merchant"

    def test_a_cancelled_line_keeps_amazons_status_verbatim(self, content: bytes) -> None:
        line = by_key(parse_orders_report(content).lines)[("111-1000000-0000003", "WIDGET-12")]

        assert line.order_status == "Cancelled"
        assert line.item_status == "Cancelled"
        assert line.quantity_ordered == 0
        assert line.item_price is None
        assert line.currency is None

    def test_a_pending_line_has_no_price_yet(self, content: bytes) -> None:
        line = by_key(parse_orders_report(content).lines)[("111-1000000-0000004", "WIDGET-12")]

        assert line.order_status == "Pending"
        assert line.item_status == "Unshipped"
        assert line.item_price is None
        assert line.currency == "USD"

    def test_repeated_order_sku_sums_quantity_and_keeps_the_latest_update(
        self, content: bytes
    ) -> None:
        line = by_key(parse_orders_report(content).lines)[("111-1000000-0000005", "WIDGET-12")]

        assert line.quantity_ordered == 5
        assert line.last_updated_at == datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
        assert line.raw["quantity"] == "3"  # the latest line's own value

    def test_a_missing_asin_is_none_not_empty_string(self, content: bytes) -> None:
        line = by_key(parse_orders_report(content).lines)[("111-1000000-0000006", "NOASIN-1")]

        assert line.asin is None

    def test_a_latin1_product_name_does_not_break_the_row(self, content: bytes) -> None:
        """Both encodings decode the accented name correctly; the row loads."""
        result = parse_orders_report(content)
        line = by_key(result.lines)[("111-1000000-0000007", "CAFE-1")]

        assert line.asin == "B000CAFE01"
        assert result.encoding == ("latin-1" if content is FIXTURE_LATIN1 else "utf-8")

    def test_a_zero_quantity_line_is_kept(self, content: bytes) -> None:
        line = by_key(parse_orders_report(content).lines)[("111-1000000-0000008", "ZERO-1")]

        assert line.quantity_ordered == 0


class TestPiiIsNeverRetained:
    def test_raw_contains_exactly_the_required_columns(self) -> None:
        for line in parse_orders_report(FIXTURE_UTF8).lines:
            assert set(line.raw) == set(REQUIRED_COLUMNS)

    def test_no_ship_column_and_no_product_name_survive(self) -> None:
        for line in parse_orders_report(FIXTURE_UTF8).lines:
            assert not any(key.startswith("ship-") for key in line.raw)
            assert "product-name" not in line.raw
            assert "SPRINGFIELD" not in repr(line)
            assert "62704" not in repr(line)


class TestRowLevelFailures:
    def test_a_bad_quantity_fails_only_that_row(self) -> None:
        content = (HEADER + "\n" + row("111-1", "A", qty="two") + "\n" + row("111-2", "B")).encode()

        result = parse_orders_report(content)

        assert result.rows_seen == 2
        assert result.rows_failed == 1
        assert result.errors == [{"row": 1, "reason": "quantity is not an integer: 'two'"}]
        assert [line.amazon_order_id for line in result.lines] == ["111-2"]

    def test_a_negative_quantity_is_rejected(self) -> None:
        result = parse_orders_report((HEADER + "\n" + row("111-1", "A", qty="-1")).encode())

        assert result.rows_failed == 1
        assert "negative" in result.errors[0]["reason"]

    def test_a_bad_timestamp_is_rejected(self) -> None:
        result = parse_orders_report(
            (HEADER + "\n" + row("111-1", "A", purchase="yesterday")).encode()
        )

        assert result.rows_failed == 1
        assert "purchase-date" in result.errors[0]["reason"]

    def test_a_blank_order_id_or_sku_is_rejected(self) -> None:
        content = (HEADER + "\n" + row("", "A") + "\n" + row("111-1", "  ")).encode()

        result = parse_orders_report(content)

        assert result.rows_failed == 2
        assert result.lines == []

    def test_a_price_without_currency_is_dropped_not_stored(self) -> None:
        """The table forbids a price with no currency; raw still shows it."""
        result = parse_orders_report((HEADER + "\n" + row("111-1", "A", currency="")).encode())

        [line] = result.lines
        assert line.item_price is None
        assert line.raw["item-price"] == "19.99"

    def test_timestamps_in_other_offsets_are_converted_to_utc(self) -> None:
        result = parse_orders_report(
            (HEADER + "\n" + row("111-1", "A", purchase="2026-09-10T10:00:00-04:00")).encode()
        )

        assert result.lines[0].purchase_date == datetime(2026, 9, 10, 14, 0, tzinfo=UTC)

    def test_a_zulu_timestamp_is_accepted(self) -> None:
        result = parse_orders_report(
            (HEADER + "\n" + row("111-1", "A", updated="2026-09-10T10:00:00Z")).encode()
        )

        assert result.lines[0].last_updated_at == datetime(2026, 9, 10, 10, 0, tzinfo=UTC)


class TestReportFormat:
    def test_a_missing_required_column_fails_the_report(self) -> None:
        header = HEADER.replace("\tlast-updated-date", "")
        content = (header + "\n" + row("111-1", "A")).encode()

        with pytest.raises(ReportFormatError, match="last-updated-date"):
            parse_orders_report(content)

    def test_an_empty_report_is_not_an_error(self) -> None:
        result = parse_orders_report((HEADER + "\n").encode())

        assert result.rows_seen == 0
        assert result.lines == []

    def test_a_header_only_of_wrong_columns_names_all_that_are_missing(self) -> None:
        with pytest.raises(ReportFormatError) as excinfo:
            parse_orders_report(b"foo\tbar\n1\t2\n")

        for column in REQUIRED_COLUMNS:
            assert column in str(excinfo.value)


class TestWindows:
    NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

    def test_a_valid_window(self) -> None:
        validate_window(
            datetime(2026, 8, 16, tzinfo=UTC), datetime(2026, 9, 15, tzinfo=UTC), now=self.NOW
        )

    def test_naive_datetimes_are_refused(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            validate_window(datetime(2026, 9, 1), datetime(2026, 9, 2, tzinfo=UTC), now=self.NOW)

    def test_a_window_ending_in_the_future_is_refused(self) -> None:
        with pytest.raises(ValueError, match="future"):
            validate_window(
                datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 16, tzinfo=UTC), now=self.NOW
            )

    def test_a_window_longer_than_the_report_limit_is_refused(self) -> None:
        with pytest.raises(ValueError, match=f"at most {MAX_WINDOW_DAYS} days"):
            validate_window(
                datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 9, 15, tzinfo=UTC), now=self.NOW
            )

    def test_an_inverted_window_is_refused(self) -> None:
        with pytest.raises(ValueError, match="after window_start"):
            validate_window(
                datetime(2026, 9, 2, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC), now=self.NOW
            )

    def test_trailing_window_is_the_report_limit_ending_now(self) -> None:
        start, end = trailing_window(now=self.NOW)

        assert end == self.NOW
        assert (end - start).days == MAX_WINDOW_DAYS
        validate_window(start, end, now=self.NOW)  # always valid by construction

    def test_trailing_window_cannot_exceed_the_report_limit(self) -> None:
        with pytest.raises(ValueError, match=f"between 1 and {MAX_WINDOW_DAYS}"):
            trailing_window(now=self.NOW, days=35)
