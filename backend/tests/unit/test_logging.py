"""Structured logging behaviour."""

from __future__ import annotations

import json

import pytest

from app.core.config import Settings
from app.core.logging import configure_logging, get_logger


def test_log_lines_are_single_json_objects(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(log_level="INFO", log_format="json"))

    get_logger("test").info("import.started", batch_id="abc123", row_count=42)

    line = capsys.readouterr().out.strip()
    payload = json.loads(line)

    assert payload["event"] == "import.started"
    assert payload["batch_id"] == "abc123"
    assert payload["row_count"] == 42
    assert payload["level"] == "info"
    assert payload["timestamp"].endswith("Z")


def test_console_format_is_not_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(log_level="INFO", log_format="console"))

    get_logger("test").info("human.readable")

    out = capsys.readouterr().out
    assert "human.readable" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out.strip())


def test_log_level_is_respected(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(log_level="WARNING", log_format="json"))

    logger = get_logger("test")
    logger.info("suppressed.event")
    logger.warning("emitted.event")

    out = capsys.readouterr().out
    assert "suppressed.event" not in out
    assert "emitted.event" in out
