"""Secrets must not appear in any representation of the settings object.

The failure this guards against is mundane and common: someone logs the settings
at startup, or an exception repr includes them, and a connection password ends
up in a log aggregator that is retained for a year and readable by everyone.
"""

from __future__ import annotations

import json

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import INSECURE_DEV_JWT_SECRET, Settings

DB_PASSWORD = "d0-not-leak-this-db-password"
JWT_SECRET = "d0-not-leak-this-signing-key-which-is-long-enough"
NINEYARD_PASSWORD = "d0-not-leak-this-nineyard-password"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url=SecretStr(f"postgresql+psycopg://prms:{DB_PASSWORD}@localhost:5432/prms"),
        auth_jwt_secret=SecretStr(JWT_SECRET),
        nineyard_password=SecretStr(NINEYARD_PASSWORD),
    )


ALL_SECRETS = (DB_PASSWORD, JWT_SECRET, NINEYARD_PASSWORD)


def test_repr_does_not_leak_secrets(settings: Settings) -> None:
    rendered = repr(settings)

    for secret in ALL_SECRETS:
        assert secret not in rendered
    assert "**********" in rendered


def test_str_does_not_leak_secrets(settings: Settings) -> None:
    rendered = str(settings)

    for secret in ALL_SECRETS:
        assert secret not in rendered


def test_json_dump_does_not_leak_secrets(settings: Settings) -> None:
    rendered = settings.model_dump_json()

    for secret in ALL_SECRETS:
        assert secret not in rendered


def test_safe_dump_does_not_leak_secrets(settings: Settings) -> None:
    """The representation intended for logging and diagnostics."""
    rendered = json.dumps(settings.safe_dump())

    for secret in ALL_SECRETS:
        assert secret not in rendered


def test_a_formatted_log_message_does_not_leak_secrets(settings: Settings) -> None:
    """The realistic accident: f-stringing settings into a log line."""
    rendered = f"starting with {settings}"

    for secret in ALL_SECRETS:
        assert secret not in rendered


def test_secret_values_are_still_reachable_deliberately(settings: Settings) -> None:
    """Masking must not make the value unusable — only inconvenient to leak."""
    assert DB_PASSWORD in settings.database_url.get_secret_value()
    assert settings.auth_jwt_secret.get_secret_value() == JWT_SECRET
    assert settings.nineyard_password is not None
    assert settings.nineyard_password.get_secret_value() == NINEYARD_PASSWORD


def test_credentials_are_typed_as_secrets() -> None:
    """A tripwire: adding a credential as a plain str should fail this."""
    for field_name in ("database_url", "auth_jwt_secret", "nineyard_password"):
        annotation = Settings.model_fields[field_name].annotation
        assert annotation is not None
        assert "SecretStr" in str(annotation), f"{field_name} is not a SecretStr"


class TestProductionGuards:
    """Production must not start on development defaults."""

    def test_the_shipped_dev_signing_key_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="shipped development key"):
            Settings(app_env="production", auth_jwt_secret=SecretStr(INSECURE_DEV_JWT_SECRET))

    def test_dev_auth_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="DEV_AUTH_ENABLED"):
            Settings(
                app_env="production",
                auth_jwt_secret=SecretStr(JWT_SECRET),
                dev_auth_enabled=True,
            )

    def test_error_detail_exposure_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="EXPOSE_ERROR_DETAILS"):
            Settings(
                app_env="production",
                auth_jwt_secret=SecretStr(JWT_SECRET),
                expose_error_details=True,
            )

    def test_a_correctly_configured_production_starts(self) -> None:
        production = Settings(app_env="production", auth_jwt_secret=SecretStr(JWT_SECRET))

        assert production.is_production
        assert not production.dev_auth_enabled

    def test_development_may_use_the_defaults(self) -> None:
        """The guards must not make local development painful."""
        local = Settings(app_env="local", dev_auth_enabled=True, expose_error_details=True)

        assert not local.is_production
