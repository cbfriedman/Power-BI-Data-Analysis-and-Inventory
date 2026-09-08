"""The authenticated path, end to end against a real database.

The unit tests prove that unauthenticated requests are rejected. These prove the
other half — that a valid credential works, that roles come from the database
rather than the token, and that a revocation takes effect at once.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import RoleCode
from app.db.session import get_db
from app.main import create_app
from app.models import AuditEvent, User, UserRole
from app.services.roles import assign_role, ensure_system_roles
from tests.integration import factories

pytestmark = pytest.mark.integration


@pytest.fixture
def api_settings() -> Settings:
    return Settings(
        app_env="test",
        app_name="prms-api-test",
        log_level="WARNING",
        dev_auth_enabled=True,
        auth_jwt_secret=SecretStr("integration-test-signing-key-at-least-32-chars"),
    )


@pytest.fixture
def client(db_session: Session, api_settings: Settings) -> Iterator[TestClient]:
    """A client whose requests run against the rolled-back test session."""
    application = create_app(api_settings)
    application.dependency_overrides[get_db] = lambda: db_session
    with TestClient(application) as test_client:
        yield test_client
    application.dependency_overrides.clear()


def _make_user_with_role(db_session: Session, role: RoleCode) -> tuple[str, User]:
    organization = factories.make_organization(db_session)
    user = factories.make_user(db_session, organization, email="buyer@example.test")
    roles = ensure_system_roles(db_session, organization.id)
    assign_role(db_session, user=user, role=roles[role])
    db_session.flush()
    return user.email, user


class TestDevTokenFlow:
    def test_a_token_authenticates_a_subsequent_request(
        self, client: TestClient, db_session: Session
    ) -> None:
        email, _user = _make_user_with_role(db_session, RoleCode.PURCHASING_MANAGER)

        issued = client.post("/api/v1/auth/dev-token", json={"email": email})
        assert issued.status_code == 201
        token = issued.json()["access_token"]

        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert me.status_code == 200
        body = me.json()
        assert body["email"] == email
        assert body["roles"] == ["PURCHASING_MANAGER"]

    def test_the_token_itself_is_never_written_to_the_audit_trail(
        self, client: TestClient, db_session: Session
    ) -> None:
        email, _ = _make_user_with_role(db_session, RoleCode.VIEWER)

        token = client.post("/api/v1/auth/dev-token", json={"email": email}).json()["access_token"]

        events = db_session.query(AuditEvent).filter_by(action="auth.dev_token_issued").all()
        assert len(events) == 1
        assert token not in str(events[0].summary)
        assert token not in str(events[0].after)

    def test_an_unknown_email_is_indistinguishable_from_a_disabled_endpoint(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Whether an address is registered is not public information."""
        factories.make_organization(db_session)

        response = client.post("/api/v1/auth/dev-token", json={"email": "nobody@example.test"})

        assert response.status_code == 404

    def test_an_inactive_user_cannot_obtain_a_token(
        self, client: TestClient, db_session: Session
    ) -> None:
        organization = factories.make_organization(db_session)
        factories.make_user(db_session, organization, email="retired@example.test", is_active=False)
        db_session.flush()

        response = client.post("/api/v1/auth/dev-token", json={"email": "retired@example.test"})

        assert response.status_code == 404


class TestAuthorizationReadsTheDatabase:
    def test_a_revoked_role_stops_applying_immediately(
        self, client: TestClient, db_session: Session
    ) -> None:
        """The reason roles are not trusted from token claims.

        The token still carries PURCHASING_MANAGER, but the grant is gone, so
        the effective role set is empty on the very next request.
        """
        email, user = _make_user_with_role(db_session, RoleCode.PURCHASING_MANAGER)
        token = client.post("/api/v1/auth/dev-token", json={"email": email}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/auth/me", headers=headers).json()["roles"] == [
            "PURCHASING_MANAGER"
        ]

        db_session.execute(delete(UserRole).where(UserRole.user_id == user.id))
        db_session.flush()

        assert client.get("/api/v1/auth/me", headers=headers).json()["roles"] == []

    def test_a_deactivated_user_is_rejected_despite_a_valid_token(
        self, client: TestClient, db_session: Session
    ) -> None:
        email, user = _make_user_with_role(db_session, RoleCode.VIEWER)
        token = client.post("/api/v1/auth/dev-token", json={"email": email}).json()["access_token"]

        user.is_active = False
        db_session.flush()

        response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401
