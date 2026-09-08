"""Authentication and authorization foundation.

The shape here is chosen so that Microsoft Entra ID can replace the development
backend without touching anything that consumes it. Everything downstream —
route dependencies, the audit service, role checks — depends on
:class:`Principal` and :class:`AuthenticationBackend`, never on how a token was
obtained or validated.

* :class:`DevJwtAuthenticationBackend` signs and verifies short-lived HS256
  tokens issued by this application. Development only; it refuses to operate
  outside it.
* An Entra backend would implement the same protocol, validating RS256 tokens
  against Microsoft's JWKS and mapping the ``roles`` or ``groups`` claim onto
  :class:`RoleCode`. See docs/security.md.

Authorization is always resolved from the database, never from token claims. A
role revoked a minute ago must not stay effective until an access token expires.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AuthenticationError, AuthorizationError
from app.models.identity import Role, User, UserRole


class RoleCode(StrEnum):
    """The system roles every organization gets.

    Organizations may define additional roles of their own — ``roles.code`` is
    free text — but these four are seeded, marked ``is_system``, and are the
    only ones the application itself reasons about.
    """

    ADMIN = "ADMIN"
    PURCHASING_MANAGER = "PURCHASING_MANAGER"
    DATA_OPERATOR = "DATA_OPERATOR"
    VIEWER = "VIEWER"


#: Human-readable descriptions, used when seeding and in the admin interface.
SYSTEM_ROLE_DEFINITIONS: dict[RoleCode, tuple[str, str]] = {
    RoleCode.ADMIN: (
        "Administrator",
        "Full access, including user and role administration.",
    ),
    RoleCode.PURCHASING_MANAGER: (
        "Purchasing Manager",
        "Approves product mappings and manages the out-of-stock watchlist.",
    ),
    RoleCode.DATA_OPERATOR: (
        "Data Operator",
        "Manages vendors and import profiles, and runs imports.",
    ),
    RoleCode.VIEWER: (
        "Viewer",
        "Read-only access to catalog, imports, and reports.",
    ),
}


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated actor.

    Frozen because nothing downstream should be able to grant itself a role
    mid-request.
    """

    user_id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    display_name: str
    roles: frozenset[RoleCode]

    def has_role(self, role: RoleCode) -> bool:
        return role in self.roles

    def has_any_role(self, roles: Iterable[RoleCode]) -> bool:
        return any(role in self.roles for role in roles)

    @property
    def is_admin(self) -> bool:
        return RoleCode.ADMIN in self.roles

    def require_roles(self, roles: Iterable[RoleCode]) -> None:
        """Raise :class:`AuthorizationError` unless one of ``roles`` is held.

        ADMIN satisfies every requirement; it is the role that exists precisely
        so an administrator is never locked out of their own system.
        """
        required = tuple(roles)
        if not required or self.is_admin or self.has_any_role(required):
            return
        raise AuthorizationError(
            "You do not have permission to perform this action.",
            details={"required_roles": sorted(role.value for role in required)},
        )


@runtime_checkable
class AuthenticationBackend(Protocol):
    """How a bearer credential becomes a :class:`Principal`.

    One method, so swapping the implementation is a one-line change in the
    dependency wiring.
    """

    def authenticate(self, token: str, session: Session) -> Principal:
        """Validate ``token`` and return the actor, or raise AuthenticationError."""
        ...


def load_principal(session: Session, user_id: uuid.UUID) -> Principal:
    """Build a Principal from current database state.

    Deliberately not from token claims: roles are read fresh on every request so
    a revocation takes effect immediately rather than at token expiry. An
    inactive user is rejected for the same reason.
    """
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("The account is unknown or inactive.")

    codes = session.execute(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    ).scalars()

    roles = frozenset(RoleCode(code) for code in codes if code in RoleCode.__members__)

    return Principal(
        user_id=user.id,
        organization_id=user.organization_id,
        email=user.email,
        display_name=user.display_name,
        roles=roles,
    )


class DevJwtAuthenticationBackend:
    """Symmetrically signed tokens issued by this application.

    For local development and automated tests only. It is not a credential
    system: there is no password check, because inventing one would be work
    thrown away when Entra ID arrives, and a half-built credential store is
    worse than none. The token endpoint that uses this is gated on
    ``DEV_AUTH_ENABLED`` *and* refuses to run in production.
    """

    algorithm = "HS256"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def issue_token(self, principal: Principal, *, now: datetime | None = None) -> tuple[str, int]:
        """Mint a token for ``principal``. Returns the token and its lifetime."""
        issued_at = now or datetime.now(UTC)
        ttl = timedelta(minutes=self._settings.auth_token_ttl_minutes)
        claims: dict[str, Any] = {
            "sub": str(principal.user_id),
            "org": str(principal.organization_id),
            "email": principal.email,
            "name": principal.display_name,
            # Present for debugging only. Authorization reads the database, so a
            # tampered or stale role claim confers nothing.
            "roles": sorted(role.value for role in principal.roles),
            "iss": self._settings.auth_issuer,
            "aud": self._settings.auth_audience,
            "iat": issued_at,
            "exp": issued_at + ttl,
        }
        token = jwt.encode(
            claims,
            self._settings.auth_jwt_secret.get_secret_value(),
            algorithm=self.algorithm,
        )
        return token, int(ttl.total_seconds())

    def authenticate(self, token: str, session: Session) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._settings.auth_jwt_secret.get_secret_value(),
                # Pinned explicitly. Accepting the token's own `alg` is the
                # classic JWT vulnerability.
                algorithms=[self.algorithm],
                audience=self._settings.auth_audience,
                issuer=self._settings.auth_issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("The access token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            # One message for every validation failure: distinguishing "bad
            # signature" from "wrong audience" only helps an attacker.
            raise AuthenticationError("The access token is not valid.") from exc

        try:
            user_id = uuid.UUID(str(claims["sub"]))
        except (KeyError, ValueError) as exc:
            raise AuthenticationError("The access token is not valid.") from exc

        return load_principal(session, user_id)


def build_authentication_backend(settings: Settings) -> AuthenticationBackend:
    """Select the authentication backend for this environment.

    The single place to change when Entra ID is introduced.
    """
    return DevJwtAuthenticationBackend(settings)
