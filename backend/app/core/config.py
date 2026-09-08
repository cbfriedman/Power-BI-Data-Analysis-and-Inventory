"""Application configuration.

All configuration is read from environment variables through this single typed
settings object. No secret, connection string, or credential is ever hardcoded
or committed (CLAUDE.md §4).

Every credential is typed ``SecretStr``, so it cannot be printed by accident:
Pydantic renders it as ``**********`` in reprs, ``str()``, and JSON dumps. Code
that genuinely needs the value asks for it explicitly with
``.get_secret_value()``, which makes each such use greppable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.redaction import redact_mapping

LogFormat = Literal["json", "console"]

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_ROOT.parent

# Resolved absolutely, because a relative ".env" is read from the working
# directory: running from backend/ would silently miss the repository-root file
# and fall back to defaults. Later entries win, so a backend-local .env can
# override the shared one. In containers there is no file at all and the values
# arrive as real environment variables.
_ENV_FILES = (_REPO_ROOT / ".env", _BACKEND_ROOT / ".env")

# Environment names treated as production for the purpose of refusing insecure
# defaults and hiding error detail.
PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod"})

# The shipped development signing key. Recognised by name so the application can
# refuse to start with it outside development.
INSECURE_DEV_JWT_SECRET = "insecure-development-signing-key-change-me"

# RFC 7518 §3.2: an HS256 key should be at least as long as the hash output.
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Typed application settings sourced from the environment."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
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
    # SecretStr: a DSN carries a password, so it is a credential, not config.
    # Overridden by DATABASE_URL in every real environment; the default points
    # at a local PostgreSQL and is deliberately not a working production value.
    database_url: SecretStr = SecretStr("postgresql+psycopg://prms:prms@localhost:5432/prms")

    # --- Authentication ------------------------------------------------------
    # HS256 signing key for the development authentication backend. Replaced
    # wholesale when Microsoft Entra ID is introduced — see docs/security.md.
    auth_jwt_secret: SecretStr = SecretStr(INSECURE_DEV_JWT_SECRET)
    auth_token_ttl_minutes: int = 480
    auth_issuer: str = "prms-dev"
    auth_audience: str = "prms-api"

    # Gates the development token endpoint. Off by default and refused outright
    # in production, so an unset environment cannot silently expose it.
    dev_auth_enabled: bool = False

    # --- Errors --------------------------------------------------------------
    # When true, unhandled errors return the exception type and message to the
    # client. Never enabled in production: forced off by the validator below.
    expose_error_details: bool = False

    # --- Nineyard integration ------------------------------------------------
    # The authentication shape is observed, not assumed: Nineyard issues a bearer
    # token in exchange for an email/password/companyId triple, so there is no
    # API key. Credentials are unset by default; the diagnostic tool refuses to
    # run without them rather than inventing a fallback.
    nineyard_base_url: str = "https://backyard.nineyard.com"
    nineyard_email: str | None = None
    nineyard_password: SecretStr | None = None
    nineyard_company_id: int | None = None
    nineyard_timeout_seconds: float = 30.0
    # Applies to transient failures only — see integrations/nineyard/client.py.
    nineyard_max_attempts: int = 3

    @property
    def has_nineyard_credentials(self) -> bool:
        return (
            self.nineyard_email is not None
            and self.nineyard_password is not None
            and self.nineyard_company_id is not None
        )

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

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in PRODUCTION_ENVIRONMENTS

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

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalise_database_scheme(cls, value: object) -> object:
        """Accept the DSN shape managed platforms actually hand out.

        Railway, Render, Heroku and friends inject ``postgres://`` or
        ``postgresql://``. SQLAlchemy reads the scheme to pick a driver, and
        without an explicit ``+psycopg`` it reaches for psycopg2, which is not
        installed — so the app dies at first connection with a confusing
        ModuleNotFoundError rather than anything about configuration.

        Rewriting the scheme here means the platform's variable can be used
        as-is, with no manual re-assembly of the DSN per environment.
        """
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw, str):
            return value

        for prefix in ("postgresql+", "postgres+"):
            if raw.startswith(prefix):
                return value  # A driver is already named; leave it alone.

        for prefix in ("postgresql://", "postgres://"):
            if raw.startswith(prefix):
                return SecretStr("postgresql+psycopg://" + raw[len(prefix) :])

        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("auth_jwt_secret")
    @classmethod
    def _require_a_strong_signing_key(cls, value: SecretStr) -> SecretStr:
        """HS256 keys shorter than 32 bytes are weak (RFC 7518 §3.2)."""
        if len(value.get_secret_value()) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(f"AUTH_JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters")
        return value

    @model_validator(mode="after")
    def _refuse_insecure_production_configuration(self) -> Settings:
        """Fail fast rather than run production on development defaults.

        Each of these is a configuration mistake that is invisible at runtime
        until it is exploited, so the application refuses to start instead.
        """
        if not self.is_production:
            return self

        problems: list[str] = []
        if self.auth_jwt_secret.get_secret_value() == INSECURE_DEV_JWT_SECRET:
            problems.append("AUTH_JWT_SECRET is still the shipped development key")
        if self.dev_auth_enabled:
            problems.append("DEV_AUTH_ENABLED must be false in production")
        if self.expose_error_details:
            problems.append("EXPOSE_ERROR_DETAILS must be false in production")

        if problems:
            raise ValueError(f"Refusing to start in {self.app_env!r}: " + "; ".join(problems))
        return self

    def safe_dump(self) -> dict[str, Any]:
        """A representation safe to log or return from a diagnostics endpoint.

        Secrets are already masked by ``SecretStr``; the redaction pass catches
        anything sensitive that arrived under a plain string field.
        """
        return redact_mapping(self.model_dump(mode="json"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Cached so the environment is read once. Tests clear the cache when they need
    to exercise a different configuration.
    """
    return Settings()
