"""Log redaction (requirement 6).

The interesting cases are the ones where a credential arrives somewhere nobody
thought to guard: nested in a dict, inside a free-text message, in a DSN logged
by a driver, or on a log record from a third-party library that never touches
structlog.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.core.config import Settings
from app.core.logging import configure_logging, get_logger
from app.core.redaction import REDACTED, is_sensitive_key, redact_mapping, redact_text


class TestSensitiveKeys:
    @pytest.mark.parametrize(
        "key",
        [
            "password",
            "Password",
            "user_password",
            "passwd",
            "authorization",
            "Authorization",
            "HTTP_AUTHORIZATION",
            "access_token",
            "refresh_token",
            "id_token",
            "bearer_token",
            "api_key",
            "apiKey",
            "X-API-Key",
            "client_secret",
            "auth_jwt_secret",
            "private_key",
            "credential",
            "Cookie",
            "database_url",
            "dsn",
        ],
    )
    def test_sensitive_keys_are_recognised(self, key: str) -> None:
        assert is_sensitive_key(key)

    @pytest.mark.parametrize(
        "key",
        ["email", "user_id", "vendor_code", "token_type", "expires_in", "status_code"],
    )
    def test_ordinary_keys_are_left_alone(self, key: str) -> None:
        assert not is_sensitive_key(key)


class TestMappingRedaction:
    def test_authorization_header_is_redacted(self) -> None:
        """The headline case: a request-header dump must not leak the token."""
        event = {
            "event": "request.received",
            "headers": {
                "Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl",
                "Content-Type": "application/json",
            },
        }

        redacted = redact_mapping(event)

        assert redacted["headers"]["Authorization"] == REDACTED
        # Non-sensitive neighbours survive, or the log becomes useless.
        assert redacted["headers"]["Content-Type"] == "application/json"
        assert "eyJhbGciOiJIUzI1NiJ9" not in json.dumps(redacted)

    def test_passwords_are_redacted_at_any_depth(self) -> None:
        event = {"user": {"profile": {"password": "hunter2", "email": "a@b.test"}}}

        redacted = redact_mapping(event)

        assert redacted["user"]["profile"]["password"] == REDACTED
        assert redacted["user"]["profile"]["email"] == "a@b.test"

    def test_secrets_inside_lists_are_redacted(self) -> None:
        event = {"attempts": [{"api_key": "sk-live-abc123"}, {"api_key": "sk-live-def456"}]}

        redacted = redact_mapping(event)

        assert all(item["api_key"] == REDACTED for item in redacted["attempts"])
        assert "sk-live" not in json.dumps(redacted)

    def test_a_non_string_secret_is_still_masked(self) -> None:
        """A sensitive key never has a value worth partially preserving."""
        assert redact_mapping({"api_key": 12345})["api_key"] == REDACTED

    def test_a_deeply_nested_structure_terminates(self) -> None:
        """Depth is capped, so a pathological payload cannot hang the logger."""
        event: dict[str, object] = {"level": "leaf"}
        for _ in range(50):
            event = {"nested": event}

        redact_mapping(event)  # must return rather than recurse forever


class TestTextRedaction:
    def test_bearer_token_in_free_text(self) -> None:
        masked = redact_text("calling api with Authorization: Bearer abc123def456ghi")

        assert "abc123def456ghi" not in masked
        assert REDACTED in masked

    def test_bare_jwt_in_free_text(self) -> None:
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhYmMifQ.Zm9vYmFyc2lnbmF0dXJl"

        masked = redact_text(f"token was {token}")

        assert token not in masked

    def test_database_url_password_is_masked(self) -> None:
        """A DSN in an exception message is a common accidental leak."""
        masked = redact_text(
            "could not connect to postgresql+psycopg://prms:sup3rs3cret@db:5432/prms"
        )

        assert "sup3rs3cret" not in masked
        # The rest stays legible, which is the whole point of masking rather
        # than dropping the message.
        assert "db:5432/prms" in masked

    def test_inline_assignment_is_masked(self) -> None:
        masked = redact_text("retrying with api_key=sk-live-9f8e7d and mode=fast")

        assert "sk-live-9f8e7d" not in masked
        assert "mode=fast" in masked


class TestLoggingPipeline:
    def test_authorization_header_never_reaches_the_output(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """End to end through the real logging configuration."""
        configure_logging(Settings(log_level="INFO", log_format="json"))

        get_logger("test").info(
            "request.received",
            headers={"Authorization": "Bearer super-secret-token-value"},
            password="hunter2",
        )

        line = capsys.readouterr().out.strip()
        payload = json.loads(line)

        assert "super-secret-token-value" not in line
        assert "hunter2" not in line
        assert payload["headers"]["Authorization"] == REDACTED
        assert payload["password"] == REDACTED
        # The event itself is still readable.
        assert payload["event"] == "request.received"

    def test_third_party_library_logs_are_redacted_too(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Records that never pass through structlog still get scrubbed.

        A driver logging its connection string is the realistic version of this,
        and it is exactly the leak that call-site discipline cannot prevent.
        """
        configure_logging(Settings(log_level="INFO", log_format="json"))

        logging.getLogger("some.third.party").info(
            "connecting to postgresql://prms:leaked-password@db:5432/prms"
        )

        out = capsys.readouterr().out
        assert "leaked-password" not in out
        assert REDACTED in out
