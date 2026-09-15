"""The amazon_poc command line: argument parsing and table formatting. No network."""

from __future__ import annotations

import uuid

import pytest

from app.cli.amazon_poc import (
    DEFAULT_ORDER_DAYS,
    EXIT_CONFIGURATION,
    EXIT_OK,
    EXIT_RUN_FAILED,
    EXIT_UNEXPECTED,
    VELOCITY_COLUMNS,
    Outcome,
    build_parser,
    format_velocity_table,
    main,
)
from app.models.enums import MappingStatus, MatchMethod
from app.services.amazon_velocity import VelocityRow

PRODUCT = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")


def velocity_row(**overrides: object) -> VelocityRow:
    values: dict[str, object] = {
        "seller_sku": "WIDGET-12",
        "asin": "B000TEST01",
        "product_id": PRODUCT,
        "catalog_item_number": "CIN-100",
        "upc": "012345678905",
        "units_7": 7,
        "units_14": 28,
        "units_30": 61,
        "fulfillable": 40,
        "fbm_quantity": 5,
        "inbound": 160,
        "mapping_status": MappingStatus.APPROVED,
        "mapping_method": MatchMethod.AMAZON_SKU_MAPPING,
    }
    values.update(overrides)
    return VelocityRow(**values)  # type: ignore[arg-type]


class TestParsing:
    def test_every_subcommand_parses(self) -> None:
        parser = build_parser()

        assert parser.parse_args(["auth"]).command == "auth"
        assert parser.parse_args(["sync-inventory"]).command == "sync-inventory"
        assert parser.parse_args(["sync-listings"]).command == "sync-listings"
        assert parser.parse_args(["run"]).command == "run"

    def test_sync_orders_defaults_and_accepts_days(self) -> None:
        parser = build_parser()

        assert parser.parse_args(["sync-orders"]).days == DEFAULT_ORDER_DAYS
        assert parser.parse_args(["sync-orders", "--days", "7"]).days == 7
        assert parser.parse_args(["run", "--days", "10"]).days == 10

    def test_velocity_defaults_and_options(self) -> None:
        parser = build_parser()

        default = parser.parse_args(["velocity"])
        assert (default.level, default.top) == ("sku", None)
        chosen = parser.parse_args(["velocity", "--level", "product", "--top", "25"])
        assert (chosen.level, chosen.top) == ("product", 25)

    @pytest.mark.parametrize("argv", [["sync-orders", "--days", "0"], ["velocity", "--top", "-1"]])
    def test_non_positive_numbers_are_refused(self, argv: list[str]) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(argv)

    def test_an_unknown_level_is_refused(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["velocity", "--level", "asin"])

    def test_a_subcommand_is_required(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args([])

    def test_no_argument_accepts_a_credential(self) -> None:
        """Credentials come from the environment, never the command line."""
        help_text = build_parser().format_help().lower()

        for word in ("secret", "token", "client-id", "password"):
            assert f"--{word}" not in help_text


class TestTableFormatting:
    def test_header_and_one_row_are_aligned(self) -> None:
        table = format_velocity_table([velocity_row()])
        header, rule, row = table.splitlines()

        assert header.startswith("Seller SKU")
        for _, title in VELOCITY_COLUMNS:
            assert title in header
        assert set(rule) <= {"-", " "}
        # Numbers right-aligned under their headers: the last character of a
        # numeric column's header and value share a column.
        assert header.index("Units 30d") + len("Units 30d") == row.index("61") + len("61")
        assert "AMAZON_SKU_MAPPING" in row
        assert "2.0" in row  # avg daily 14 = 28 / 14
        assert "22.5" in row  # days of supply = (40 + 5) / 2.0

    def test_missing_values_render_as_dashes(self) -> None:
        row = velocity_row(
            asin=None,
            product_id=None,
            catalog_item_number=None,
            upc=None,
            fulfillable=None,
            fbm_quantity=None,
            inbound=None,
            units_7=0,
            units_14=0,
            units_30=0,
            mapping_status=MappingStatus.UNMAPPED,
            mapping_method=None,
        )

        line = format_velocity_table([row]).splitlines()[2]

        assert line.split()[0] == "WIDGET-12"
        assert line.count("-") >= 6  # asin, cin, upc, fulfillable, fbm, inbound, supply, mapping

    def test_days_of_supply_is_blank_when_nothing_sold(self) -> None:
        row = velocity_row(units_7=0, units_14=0, units_30=0)

        line = format_velocity_table([row]).splitlines()[2]

        assert "0.0" in line  # avg/day
        assert line.rstrip().endswith("AMAZON_SKU_MAPPING")
        assert "inf" not in line

    def test_an_empty_report_says_so(self) -> None:
        table = format_velocity_table([])

        assert "no data" in table

    def test_column_widths_grow_with_content(self) -> None:
        long_sku = velocity_row(seller_sku="A-VERY-LONG-SELLER-SKU-INDEED")
        table = format_velocity_table([velocity_row(), long_sku])
        lines = table.splitlines()

        assert all(line.startswith(("Seller SKU", "-", "WIDGET-12", "A-VERY")) for line in lines)
        assert lines[2].index("B000TEST01") == lines[3].index("B000TEST01")


class TestMainExitCodes:
    """main() maps outcomes and errors to exit codes; dispatch is stubbed."""

    def test_a_successful_outcome_prints_its_lines_and_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            "app.cli.amazon_poc.dispatch", lambda args, settings: Outcome(EXIT_OK, ["fine"])
        )

        assert main(["auth"]) == EXIT_OK
        assert capsys.readouterr().out.strip() == "fine"

    def test_a_failed_run_exits_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "app.cli.amazon_poc.dispatch",
            lambda args, settings: Outcome(EXIT_RUN_FAILED, ["orders: FAILED"]),
        )

        assert main(["sync-orders"]) == EXIT_RUN_FAILED

    def test_a_configuration_error_exits_two(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from app.integrations.amazon.errors import AmazonConfigurationError

        def boom(args: object, settings: object) -> Outcome:
            raise AmazonConfigurationError("Missing required settings: AMAZON_SELLER_ID")

        monkeypatch.setattr("app.cli.amazon_poc.dispatch", boom)

        assert main(["auth"]) == EXIT_CONFIGURATION
        assert "AMAZON_SELLER_ID" in capsys.readouterr().err

    def test_an_auth_error_exits_two_without_the_token(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from app.integrations.amazon.errors import AmazonAuthError

        def boom(args: object, settings: object) -> Outcome:
            raise AmazonAuthError("LWA refused (invalid_grant)")

        monkeypatch.setattr("app.cli.amazon_poc.dispatch", boom)

        assert main(["auth"]) == EXIT_CONFIGURATION
        err = capsys.readouterr().err
        assert "invalid_grant" in err
        assert "Atzr|" not in err

    def test_an_unexpected_error_exits_three(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(args: object, settings: object) -> Outcome:
            raise RuntimeError("disk on fire")

        monkeypatch.setattr("app.cli.amazon_poc.dispatch", boom)

        assert main(["velocity"]) == EXIT_UNEXPECTED
