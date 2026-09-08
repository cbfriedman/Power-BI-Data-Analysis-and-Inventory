"""Application configuration.

All configuration is read from environment variables through this single typed
settings object. No secret, connection string, or credential is ever hardcoded
or committed (CLAUDE.md §4).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LogFormat = Literal["json", "console"]


class Settings(BaseSettings):
    """Typed application settings sourced from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---------------------------------------------------------
    app_env: str = "local"
    app_name: str = "prms-api"
    api_v1_prefix: str = "/api/v1"

    # --- Logging -------------------------------------------------------------
    log_level: str = "INFO"
    log_format: LogFormat = "json"

    # --- Database ------------------------------------------------------------
    # Overridden by DATABASE_URL in every real environment. The default points
    # at a local PostgreSQL and is deliberately not a working production value.
    database_url: str = "postgresql+psycopg://prms:prms@localhost:5432/prms"

    # --- HTTP ----------------------------------------------------------------
    # NoDecode stops pydantic-settings from JSON-decoding the environment value
    # before validation. Without it, a plain CORS_ALLOW_ORIGINS=http://host
    # raises a JSONDecodeError at startup, because list[str] is treated as a
    # complex field and parsed as JSON first.
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # --- Storage (retained import files, ADR 0004) ---------------------------
    storage_raw_dir: str = "/storage/raw"
    storage_processed_dir: str = "/storage/processed"
    storage_rejected_dir: str = "/storage/rejected"

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        """Accept ``a,b,c`` from the environment as well as a JSON list."""
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                return value
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Cached so the environment is read once. Tests clear the cache when they need
    to exercise a different configuration.
    """
    return Settings()
