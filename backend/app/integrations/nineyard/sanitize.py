"""Structure-preserving sanitisation of API responses.

The probe needs to answer "what shape is this, and what are the fields called?"
without ever writing real customer or vendor data to disk. So values are
replaced by *descriptors* of themselves: type, length, and character class.

``"012345678905"`` becomes ``"<str len=12 digits>"`` — which is enough to
recognise a UPC without recording one. That is the whole trick: the descriptor
carries the diagnostic signal and none of the data.

Booleans and nulls are kept literally. They cannot identify anyone, and knowing
that a flag is genuinely boolean rather than ``"Y"``/``"N"`` is exactly the kind
of thing this tool exists to establish.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

from app.core.redaction import REDACTED, is_sensitive_key

#: Depth cap. A cyclic or pathologically nested payload must not hang the probe.
MAX_DEPTH: Final = 12

#: How many elements of a list to describe. The rest are summarised by count;
#: element 500 rarely has a shape that elements 1-3 did not.
DEFAULT_SAMPLE_SIZE: Final = 3

_DIGITS_RE: Final = re.compile(r"^\d+$")
_ALNUM_RE: Final = re.compile(r"^[A-Za-z0-9]+$")
_ISO_DATE_RE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2})?")
_UUID_RE: Final = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def describe_string(value: str) -> str:
    """Describe a string without reproducing it.

    The character class is the useful part: it distinguishes an all-digit
    identifier from a free-text description without revealing either.
    """
    length = len(value)
    if not value:
        return "<str empty>"
    if _UUID_RE.match(value):
        return "<str uuid>"
    if _ISO_DATE_RE.match(value):
        return f"<str len={length} datetime-like>"
    if _DIGITS_RE.match(value):
        return f"<str len={length} digits>"
    if _ALNUM_RE.match(value):
        return f"<str len={length} alphanumeric>"
    return f"<str len={length} text>"


def describe_scalar(value: Any) -> Any:
    """Describe a non-container value."""
    # Kept literal: neither can identify anything, and both are diagnostically
    # meaningful in their own right.
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return describe_string(value)
    if isinstance(value, int):
        return "<int>"
    if isinstance(value, float):
        return "<float>"
    return f"<{type(value).__name__}>"


def sanitize(
    value: Any,
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    _depth: int = 0,
) -> Any:
    """Recursively replace every value with a description of itself.

    Keys are preserved verbatim — field names are the point of the exercise.
    A key that looks sensitive is redacted outright rather than described, since
    even ``<str len=64 alphanumeric>`` under ``apiKey`` says more than it should.
    """
    if _depth >= MAX_DEPTH:
        return "<max-depth>"

    if isinstance(value, Mapping):
        described: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if is_sensitive_key(key_str):
                described[key_str] = REDACTED
            else:
                described[key_str] = sanitize(item, sample_size=sample_size, _depth=_depth + 1)
        return described

    if isinstance(value, str | bytes | bytearray):
        return describe_scalar(value if isinstance(value, str) else "<binary>")

    if isinstance(value, Sequence):
        items = list(value)
        described_items = [
            sanitize(item, sample_size=sample_size, _depth=_depth + 1)
            for item in items[:sample_size]
        ]
        if len(items) > sample_size:
            described_items.append(f"<... {len(items) - sample_size} more of {len(items)}>")
        return described_items

    return describe_scalar(value)


def field_names(records: Sequence[Any]) -> list[str]:
    """Union of the keys seen across record objects.

    A union rather than the first record's keys, because sparse payloads are
    normal: an optional field absent from record 1 and present in record 2 is
    still a field, and the probe should report it.
    """
    names: set[str] = set()
    for record in records:
        if isinstance(record, Mapping):
            names.update(str(key) for key in record)
    return sorted(names)


def field_presence(records: Sequence[Any]) -> dict[str, int]:
    """How many records carried each field.

    Distinguishes "always present" from "occasionally present", which is what
    determines whether a mapped column can be NOT NULL.
    """
    counts: dict[str, int] = {}
    for record in records:
        if isinstance(record, Mapping):
            for key in record:
                counts[str(key)] = counts.get(str(key), 0) + 1
    return dict(sorted(counts.items()))
