"""Configuration behaviour (AC-0.2)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.core.config import Settings, get_settings


def test_cors_origins_accept_comma_separated_string() -> None:
    settings = Settings(cors_allow_origins="http://a.test, http://b.test")

    assert settings.cors_allow_origins == ["http://a.test", "http://b.test"]


def test_cors_origins_accept_a_list() -> None:
    settings = Settings(cors_allow_origins=["http://a.test"])

    assert settings.cors_allow_origins == ["http://a.test"]


def test_empty_cors_origins_yield_an_empty_list() -> None:
    settings = Settings(cors_allow_origins="")

    assert settings.cors_allow_origins == []


def test_log_level_is_normalised_to_upper_case() -> None:
    assert Settings(log_level="debug").log_level == "DEBUG"


def test_settings_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("LOG_LEVEL", "warning")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://from-env.test")

    settings = Settings()

    assert settings.app_env == "staging"
    assert settings.log_level == "WARNING"
    assert settings.cors_allow_origins == ["http://from-env.test"]


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


def test_no_credential_is_hardcoded_as_a_working_default() -> None:
    """The default database URL must be an obvious local placeholder.

    This is a tripwire, not proof: it fails loudly if someone ever pastes a real
    host into the default (CLAUDE.md §4).
    """
    default_url = Settings.model_fields["database_url"].default

    assert isinstance(default_url, SecretStr)
    assert "localhost" in default_url.get_secret_value()


class TestDatabaseUrlNormalisation:
    """Managed platforms inject a DSN without a driver name.

    Railway, Render and Heroku all hand out `postgres://` or `postgresql://`.
    SQLAlchemy picks its driver from the scheme, so without `+psycopg` it
    reaches for psycopg2 — which is not installed — and the app dies at first
    connection with a ModuleNotFoundError that says nothing about config.
    """

    @pytest.mark.parametrize(
        "injected",
        ["postgres://u:p@host:5432/db", "postgresql://u:p@host:5432/db"],
    )
    def test_a_driverless_scheme_gains_psycopg(self, injected: str) -> None:
        settings = Settings(database_url=injected)

        assert settings.database_url.get_secret_value() == "postgresql+psycopg://u:p@host:5432/db"

    def test_an_explicit_driver_is_left_alone(self) -> None:
        explicit = "postgresql+asyncpg://u:p@host:5432/db"

        settings = Settings(database_url=explicit)

        assert settings.database_url.get_secret_value() == explicit

    def test_the_password_is_still_masked_after_rewriting(self) -> None:
        settings = Settings(database_url="postgres://u:sup3rs3cret@host:5432/db")

        assert "sup3rs3cret" not in repr(settings)
        assert "sup3rs3cret" in settings.database_url.get_secret_value()

    def test_a_non_postgres_url_is_untouched(self) -> None:
        settings = Settings(database_url="sqlite:///./local.db")

        assert settings.database_url.get_secret_value() == "sqlite:///./local.db"
