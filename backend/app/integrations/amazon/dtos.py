"""Typed, frozen views of what SP-API returns.

These are the only Amazon-shaped values that leave the anti-corruption layer.
Each is built from the raw payload by a ``from_payload`` classmethod that
names the SP-API field it reads, so the mapping is in one place and a renamed
upstream field fails here, loudly, rather than as a ``None`` three modules
away. No SP-API field name appears in ``app/models/`` (ADR 0007, ADR 0011).

Field names below follow the documented Selling Partner API models:
``createReport`` → ``reportId``; ``getReport`` → ``processingStatus``,
``reportDocumentId``; FBA Inventory v1 ``InventorySummary`` →
``sellerSku``, ``asin``, ``fnSku``, ``condition``, ``lastUpdatedTime``,
``totalQuantity`` and the nested ``inventoryDetails`` block.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar


class PayloadShapeError(ValueError):
    """The payload did not carry a field this layer depends on."""


def _require_str(payload: Mapping[str, Any], key: str, *, where: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise PayloadShapeError(
            f"{where}: expected a non-empty string at {key!r}; keys present: {sorted(payload)}"
        )
    return value


def _optional_str(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _optional_int(payload: Mapping[str, Any] | None, key: str) -> int | None:
    if payload is None:
        return None
    value = payload.get(key)
    # bool is an int subclass; a True here would be a shape error, not a count.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _optional_datetime(payload: Mapping[str, Any], key: str) -> datetime | None:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        return None
    try:
        # SP-API uses ISO 8601 with a trailing Z.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class ReportRequest:
    """The identifier Amazon assigned to a report we asked for."""

    report_id: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ReportRequest:
        return cls(report_id=_require_str(payload, "reportId", where="createReport"))


@dataclass(frozen=True, slots=True)
class ReportStatus:
    """Where a report is in Amazon's queue.

    ``processing_status`` is one of ``IN_QUEUE``, ``IN_PROGRESS``, ``DONE``,
    ``CANCELLED`` or ``FATAL``. ``report_document_id`` is present only once the
    status is ``DONE``.
    """

    processing_status: str
    report_document_id: str | None

    TERMINAL: ClassVar[frozenset[str]] = frozenset({"DONE", "CANCELLED", "FATAL"})

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ReportStatus:
        return cls(
            processing_status=_require_str(payload, "processingStatus", where="getReport"),
            report_document_id=_optional_str(payload, "reportDocumentId"),
        )

    @property
    def is_terminal(self) -> bool:
        return self.processing_status in self.TERMINAL

    @property
    def is_done(self) -> bool:
        return self.processing_status == "DONE"


@dataclass(frozen=True, slots=True)
class InventorySummary:
    """One seller SKU's FBA inventory position, including inbound quantities.

    Quantities are ``None`` when Amazon omitted them — which it does for the
    ``inventoryDetails`` block unless the request asked for ``details=true``,
    and for any zero-valued nested field — rather than being silently
    defaulted to ``0``. A caller that wants a number treats ``None`` as zero
    explicitly.
    """

    seller_sku: str
    asin: str | None
    fnsku: str | None
    condition: str | None
    last_updated: datetime | None
    total: int | None
    fulfillable: int | None
    inbound_working: int | None
    inbound_shipped: int | None
    inbound_receiving: int | None
    reserved_total: int | None
    unfulfillable_total: int | None
    researching_total: int | None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> InventorySummary:
        details = payload.get("inventoryDetails")
        details = details if isinstance(details, Mapping) else None

        def nested(block: str, key: str) -> int | None:
            if details is None:
                return None
            inner = details.get(block)
            return _optional_int(inner, key) if isinstance(inner, Mapping) else None

        return cls(
            seller_sku=_require_str(payload, "sellerSku", where="inventorySummaries"),
            asin=_optional_str(payload, "asin"),
            fnsku=_optional_str(payload, "fnSku"),
            condition=_optional_str(payload, "condition"),
            last_updated=_optional_datetime(payload, "lastUpdatedTime"),
            total=_optional_int(payload, "totalQuantity"),
            fulfillable=_optional_int(details, "fulfillableQuantity"),
            inbound_working=_optional_int(details, "inboundWorkingQuantity"),
            inbound_shipped=_optional_int(details, "inboundShippedQuantity"),
            inbound_receiving=_optional_int(details, "inboundReceivingQuantity"),
            reserved_total=nested("reservedQuantity", "totalReservedQuantity"),
            unfulfillable_total=nested("unfulfillableQuantity", "totalUnfulfillableQuantity"),
            researching_total=nested("researchingQuantity", "totalResearchingQuantity"),
        )
