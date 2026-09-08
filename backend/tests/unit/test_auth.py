"""Protected endpoints reject unauthenticated requests (requirements 13-15).

Every rejection here happens before the database is touched, which is why these
are unit tests: an unauthenticated request must not be able to make the API do
work on its behalf.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.api.deps import get_client_ip, require_roles
from app.core.config import Settings
from app.core.errors import AuthenticationError, AuthorizationError
from app.core.security import (
    DevJwtAuthenticationBackend,
    Principal,
    RoleCode,
    build_authentication_backend,
)
from app.main import create_app

PROTECTED_PATH = "/api/v1/auth/me"


class TestUnauthenticatedRequestsAreRejected:
    def test_no_credentials(self, client: TestClient) -> None:
        response = client.get(PROTECTED_PATH)

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"
        # RFC 7235: a 401 must say how to authenticate.
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_empty_bearer_token(self, client: TestClient) -> None:
        response = client.get(PROTECTED_PATH, headers={"Authorization": "Bearer "})

        assert response.status_code == 401

    def test_wrong_scheme(self, client: TestClient) -> None:
        response = client.get(PROTECTED_PATH, headers={"Authorization": "Basic YWJjOmRlZg=="})

        assert response.status_code == 401

    def test_garbage_token(self, client: TestClient) -> None:
        response = client.get(PROTECTED_PATH, headers={"Authorization": "Bearer not-a-jwt"})

        assert response.status_code == 401

    def test_token_signed_with_the_wrong_key(self, client: TestClient, settings: Settings) -> None:
        """A forged token must not be accepted."""
        forged = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "iss": settings.auth_issuer,
                "aud": settings.auth_audience,
                "iat": datetime.now(UTC),
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            "an-attackers-own-signing-key-of-sufficient-length",
            algorithm="HS256",
        )

        response = client.get(PROTECTED_PATH, headers={"Authorization": f"Bearer {forged}"})

        assert response.status_code == 401

    def test_expired_token(self, client: TestClient, settings: Settings) -> None:
        expired = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "iss": settings.auth_issuer,
                "aud": settings.auth_audience,
                "iat": datetime.now(UTC) - timedelta(hours=2),
                "exp": datetime.now(UTC) - timedelta(hours=1),
            },
            settings.auth_jwt_secret.get_secret_value(),
            algorithm="HS256",
        )

        response = client.get(PROTECTED_PATH, headers={"Authorization": f"Bearer {expired}"})

        assert response.status_code == 401

    def test_the_none_algorithm_is_rejected(self, settings: Settings) -> None:
        """The classic JWT attack: an unsigned token claiming ``alg: none``.

        Accepting the token's own algorithm would make every signature optional.
        """
        unsigned = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "iss": settings.auth_issuer,
                "aud": settings.auth_audience,
                "iat": datetime.now(UTC),
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            key="",
            algorithm="none",
        )
        backend = DevJwtAuthenticationBackend(settings)

        # Rejected during decode, so no session is ever needed.
        with pytest.raises(AuthenticationError):
            backend.authenticate(unsigned, session=None)  # type: ignore[arg-type]

    def test_rejection_happens_before_any_database_access(
        self, degraded_client: TestClient
    ) -> None:
        """A 401 must not depend on the database being reachable.

        If it did, an unauthenticated caller could make the API open a
        connection, and an outage would turn 401s into 503s.
        """
        response = degraded_client.get(PROTECTED_PATH)

        assert response.status_code == 401


class TestErrorEnvelope:
    def test_a_401_carries_the_correlation_id(self, client: TestClient) -> None:
        response = client.get(PROTECTED_PATH)

        body = response.json()["error"]
        assert body["request_id"] == response.headers["X-Request-ID"]

    def test_no_token_material_is_echoed_back(self, client: TestClient) -> None:
        """The rejection must not reflect the credential it rejected."""
        response = client.get(
            PROTECTED_PATH, headers={"Authorization": "Bearer super-secret-value"}
        )

        assert "super-secret-value" not in response.text


class TestRoleRequirements:
    """``require_roles`` is what will guard mutation endpoints."""

    @staticmethod
    def _principal(*roles: RoleCode) -> Principal:
        return Principal(
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            email="buyer@example.test",
            display_name="Test Buyer",
            roles=frozenset(roles),
        )

    def test_a_matching_role_passes(self) -> None:
        self._principal(RoleCode.DATA_OPERATOR).require_roles([RoleCode.DATA_OPERATOR])

    def test_a_missing_role_is_refused(self) -> None:
        with pytest.raises(AuthorizationError):
            self._principal(RoleCode.VIEWER).require_roles([RoleCode.PURCHASING_MANAGER])

    def test_admin_satisfies_every_requirement(self) -> None:
        """ADMIN exists so an administrator cannot be locked out."""
        self._principal(RoleCode.ADMIN).require_roles([RoleCode.PURCHASING_MANAGER])

    def test_any_one_of_several_roles_suffices(self) -> None:
        self._principal(RoleCode.DATA_OPERATOR).require_roles(
            [RoleCode.PURCHASING_MANAGER, RoleCode.DATA_OPERATOR]
        )

    def test_a_role_guarded_route_rejects_anonymous_callers(
        self, app: FastAPI, settings: Settings
    ) -> None:
        """Mounted here rather than shipped: the app has no mutation routes yet."""

        @app.post(
            "/api/v1/_test/guarded",
            dependencies=[Depends(require_roles(RoleCode.PURCHASING_MANAGER))],
        )
        def guarded_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        with TestClient(app) as test_client:
            response = test_client.post("/api/v1/_test/guarded")

        assert response.status_code == 401


class TestBackendSelection:
    def test_the_development_backend_is_selected_locally(self, settings: Settings) -> None:
        assert isinstance(build_authentication_backend(settings), DevJwtAuthenticationBackend)

    def test_issued_tokens_round_trip_their_claims(self, settings: Settings) -> None:
        """Claims are readable, but authorization still reads the database."""
        principal = Principal(
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            email="buyer@example.test",
            display_name="Test Buyer",
            roles=frozenset({RoleCode.VIEWER}),
        )
        backend = DevJwtAuthenticationBackend(settings)

        token, expires_in = backend.issue_token(principal)
        claims = jwt.decode(
            token,
            settings.auth_jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience=settings.auth_audience,
            issuer=settings.auth_issuer,
        )

        assert claims["sub"] == str(principal.user_id)
        assert claims["roles"] == ["VIEWER"]
        assert expires_in == settings.auth_token_ttl_minutes * 60


class TestDevTokenEndpointGating:
    def test_it_is_absent_when_dev_auth_is_disabled(self, settings: Settings) -> None:
        """Disabled it answers 404, not 403 — it should not advertise itself."""
        disabled = settings.model_copy(update={"dev_auth_enabled": False})
        application = create_app(disabled)

        with TestClient(application) as test_client:
            response = test_client.post(
                "/api/v1/auth/dev-token", json={"email": "buyer@example.test"}
            )

        assert response.status_code == 404


class TestClientAddressCapture:
    """``X-Forwarded-For`` is caller-supplied and reaches an INET column."""

    @staticmethod
    def _request_with(headers: dict[str, str], host: str | None = "203.0.113.7") -> Request:
        scope = {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": (host, 12345) if host else None,
        }
        return Request(scope)

    def test_a_valid_forwarded_address_is_used(self) -> None:
        request = self._request_with({"X-Forwarded-For": "198.51.100.4, 10.0.0.1"})

        assert get_client_ip(request) == "198.51.100.4"

    def test_an_unparseable_address_is_discarded(self) -> None:
        """Storing it would fail the INSERT and 500 the request."""
        request = self._request_with({"X-Forwarded-For": "not-an-ip-address"})

        assert get_client_ip(request) is None

    def test_an_injection_attempt_is_discarded(self) -> None:
        request = self._request_with({"X-Forwarded-For": "'); drop table audit_events;--"})

        assert get_client_ip(request) is None

    def test_ipv6_is_accepted(self) -> None:
        request = self._request_with({"X-Forwarded-For": "2001:db8::1"})

        assert get_client_ip(request) == "2001:db8::1"

    def test_it_falls_back_to_the_peer_address(self) -> None:
        assert get_client_ip(self._request_with({})) == "203.0.113.7"
