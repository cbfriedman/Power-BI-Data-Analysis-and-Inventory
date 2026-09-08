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
