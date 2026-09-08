"""Read-only Nineyard HTTP client.

**This client cannot mutate anything, structurally.** It exposes exactly one
data method, :meth:`NineyardClient.get`, and one private authentication call
hard-wired to the token path. There is no ``post``, ``put``, ``patch`` or
``delete`` to misuse, and no method that takes an HTTP verb as an argument. That
is a stronger guarantee than a policy of "don't call mutation endpoints", and a
test asserts it holds.

What is known about the API is only what has been observed (CLAUDE.md working
agreements, ADR 0007): the token endpoint, its request body, and three response
fields. Everything else — pagination, field names, envelope shape — is what the
probe exists to discover, so nothing here assumes it.

Credentials are never logged. The token is logged only as a short fingerprint,
which is a hash prefix and not a usable credential.
"""

from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Final, Self

import httpx2 as httpx
from pydantic import SecretStr

from app.core.config import Settings
from app.core.logging import get_logger
from app.integrations.nineyard.errors import (
    NineyardAuthenticationError,
    NineyardConfigurationError,
    NineyardNotFoundError,
    NineyardPermissionError,
    NineyardProtocolError,
    NineyardRateLimitError,
    NineyardServerError,
    NineyardTransportError,
    NineyardUnexpectedStatusError,
)

_logger = get_logger(__name__)

#: The one non-GET request this client makes, and the only one it can make.
AUTH_PATH: Final = "/api/OAuth/UsernameToken"

#: Statuses worth retrying. Everything else is a definite answer: retrying a 401
#: or a 404 just repeats the same mistake more slowly.
RETRYABLE_STATUSES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})

#: Upper bound on any single backoff wait, including a server-supplied
#: Retry-After. A diagnostic run must not hang for minutes on a bad header.
MAX_BACKOFF_SECONDS: Final = 30.0


@dataclass(frozen=True, slots=True)
class NineyardConfig:
    """Everything the client needs, resolved from environment variables."""

    base_url: str
    email: str
    password: SecretStr
    company_id: int
    timeout_seconds: float = 30.0
    max_attempts: int = 3

    @classmethod
    def from_settings(cls, settings: Settings) -> NineyardConfig:
        """Build from application settings, or explain precisely what is missing."""
        missing = [
            name
            for name, value in (
                ("NINEYARD_EMAIL", settings.nineyard_email),
                ("NINEYARD_PASSWORD", settings.nineyard_password),
                ("NINEYARD_COMPANY_ID", settings.nineyard_company_id),
            )
            if value is None
        ]
        if missing:
            raise NineyardConfigurationError(f"Missing required settings: {', '.join(missing)}")

        assert settings.nineyard_email is not None
        assert settings.nineyard_password is not None
        assert settings.nineyard_company_id is not None

        return cls(
            base_url=settings.nineyard_base_url.rstrip("/"),
            email=settings.nineyard_email,
            password=settings.nineyard_password,
            company_id=settings.nineyard_company_id,
            timeout_seconds=settings.nineyard_timeout_seconds,
            max_attempts=settings.nineyard_max_attempts,
        )


@dataclass(frozen=True, slots=True)
class TokenInfo:
    """An issued access token and what the response said about its lifetime.

    ``expires_in`` and ``expires`` are named after the fields the API is
    documented to return. They are optional because "documented" is not
    "observed", and the probe's job is to confirm they actually arrive.
    """

    access_token: SecretStr
    expires_in: int | None
    expires: str | None
    #: Short hash prefix. Enough to tell two tokens apart in a log; useless as a
    #: credential. The token itself is never logged.
    fingerprint: str
    #: Every top-level key the token response contained, so the probe can report
    #: the real shape rather than only the three fields we expected.
    response_keys: tuple[str, ...]


def fingerprint_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:12]


class NineyardClient:
    """A deliberately minimal, read-only Nineyard client."""

    def __init__(
        self,
        config: NineyardConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """``transport`` is injectable purely so tests never touch the network."""
        self._config = config
        self._token: TokenInfo | None = None
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=httpx.Timeout(config.timeout_seconds),
            transport=transport,
            follow_redirects=False,
            headers={"Accept": "application/json"},
        )

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @property
    def token(self) -> TokenInfo | None:
        return self._token

    @property
    def config(self) -> NineyardConfig:
        return self._config

    # -- authentication ----------------------------------------------------

    def authenticate(self) -> TokenInfo:
        """Exchange credentials for a bearer token.

        The only non-GET request this client makes, and its path is a constant —
        it cannot be pointed at anything else.
        """
        payload = {
            "email": self._config.email,
            "password": self._config.password.get_secret_value(),
            "companyId": self._config.company_id,
        }

        # Note what is *absent* from this log line: the email, the password, and
        # the token. Only the company id, which is not a secret on its own.
        _logger.info("nineyard.authenticating", company_id=self._config.company_id)

        response = self._send_with_retries("POST", AUTH_PATH, json=payload, describe="authenticate")
        self._raise_for_status(response, path=AUTH_PATH)

        body = self._decode_json(response, path=AUTH_PATH)
        if not isinstance(body, dict):
            raise NineyardProtocolError(
                f"Token response was {type(body).__name__}, expected an object.",
                status_code=response.status_code,
            )

        raw_token = body.get("accessToken")
        if not isinstance(raw_token, str) or not raw_token:
            raise NineyardProtocolError(
                "Token response contained no usable 'accessToken'. "
                f"Top-level keys present: {sorted(body)}",
                status_code=response.status_code,
            )

        expires_in = body.get("expiresIn")
        token = TokenInfo(
            access_token=SecretStr(raw_token),
            expires_in=expires_in if isinstance(expires_in, int) else None,
            expires=body.get("expires") if isinstance(body.get("expires"), str) else None,
            fingerprint=fingerprint_token(raw_token),
            response_keys=tuple(sorted(body)),
        )
        self._token = token

        _logger.info(
            "nineyard.authenticated",
            token_fingerprint=token.fingerprint,
            token_expires_in=token.expires_in,
        )
        return token

    # -- the only data method ----------------------------------------------

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        """Perform a read.

        There is no counterpart for any other verb. Adding one would remove the
        guarantee that this module cannot change anything in Nineyard.
        """
        if self._token is None:
            raise NineyardConfigurationError("authenticate() must be called before any read.")

        response = self._send_with_retries(
            "GET",
            path,
            params=params,
            headers={"Authorization": f"Bearer {self._token.access_token.get_secret_value()}"},
            describe=f"GET {path}",
        )
        self._raise_for_status(response, path=path)
        return response

    # -- internals ---------------------------------------------------------

    def _send_with_retries(
        self,
        method: str,
        path: str,
        *,
        describe: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Send, retrying only failures that could plausibly succeed next time.

        Transport errors and the statuses in :data:`RETRYABLE_STATUSES`. A 4xx
        other than 429 is a definite answer and is returned immediately for the
        caller to classify.
        """
        last_transport_error: Exception | None = None

        for attempt in range(1, self._config.max_attempts + 1):
            try:
                response = self._client.request(
                    method, path, json=json, params=params, headers=headers
                )
            except httpx.TransportError as exc:
                last_transport_error = exc
                if attempt == self._config.max_attempts:
                    break
                self._sleep_before_retry(attempt, describe=describe, reason=type(exc).__name__)
                continue

            if response.status_code in RETRYABLE_STATUSES and attempt < self._config.max_attempts:
                self._sleep_before_retry(
                    attempt,
                    describe=describe,
                    reason=f"HTTP {response.status_code}",
                    retry_after=_retry_after_seconds(response),
                )
                continue

            return response

        raise NineyardTransportError(
            f"{describe} failed after {self._config.max_attempts} attempts: "
            f"{type(last_transport_error).__name__}: {last_transport_error}"
        )

    def _sleep_before_retry(
        self,
        attempt: int,
        *,
        describe: str,
        reason: str,
        retry_after: float | None = None,
    ) -> None:
        """Exponential backoff with jitter, or the server's own Retry-After.

        Jitter matters even for a single-client diagnostic: without it, repeated
        runs synchronise onto the same retry instants.
        """
        if retry_after is not None:
            delay = min(retry_after, MAX_BACKOFF_SECONDS)
        else:
            delay = min(2.0 ** (attempt - 1), MAX_BACKOFF_SECONDS)
            delay *= 0.5 + random.random() / 2

        _logger.warning(
            "nineyard.retrying",
            request=describe,
            attempt=attempt,
            reason=reason,
            delay_seconds=round(delay, 2),
        )
        time.sleep(delay)

    def _raise_for_status(self, response: httpx.Response, *, path: str) -> None:
        """Translate a status into the exception that explains it."""
        status = response.status_code
        if 200 <= status < 300:
            return

        message = f"{path} returned HTTP {status}"
        if status == 401:
            raise NineyardAuthenticationError(message, status_code=status)
        if status == 403:
            raise NineyardPermissionError(message, status_code=status)
        if status == 404:
            raise NineyardNotFoundError(message, status_code=status)
        if status == 429:
            raise NineyardRateLimitError(
                message, status_code=status, retry_after_seconds=_retry_after_seconds(response)
            )
        if 500 <= status < 600:
            raise NineyardServerError(message, status_code=status)
        raise NineyardUnexpectedStatusError(message, status_code=status)

    def _decode_json(self, response: httpx.Response, *, path: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            content_type = response.headers.get("content-type", "unknown")
            raise NineyardProtocolError(
                f"{path} returned {content_type}, which is not decodable JSON.",
                status_code=response.status_code,
            ) from exc


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse ``Retry-After`` when it is given as a number of seconds.

    The HTTP-date form is not handled: it is rare in practice, and guessing at a
    date parse is worse than falling back to ordinary backoff.
    """
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None
