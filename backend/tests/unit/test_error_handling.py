"""Centralized exception handling (requirements 9-10).

The rule with teeth: an unhandled exception must never return a stack trace to a
client in production. A leaked traceback discloses file paths, library versions,
and sometimes query fragments containing customer data.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.main import create_app

SECRET_IN_TRACEBACK = "a-value-that-must-never-reach-a-client"


def _app_with_failing_route(settings: Settings) -> FastAPI:
    application = create_app(settings)

    @application.get("/api/v1/_test/boom")
    def boom() -> None:
        raise RuntimeError(f"internal failure involving {SECRET_IN_TRACEBACK}")

    @application.get("/api/v1/_test/not-found")
    def missing() -> None:
        raise NotFoundError("No such vendor.")

    @application.get("/api/v1/_test/conflict")
    def conflicted() -> None:
        raise ConflictError("That vendor code is already taken.", details={"code": "ACME"})

    return application


class TestProductionSafety:
    @pytest.fixture
    def production_client(self, settings: Settings) -> TestClient:
        # model_copy deliberately skips validation, so a production-shaped
        # Settings can be built here without a real signing key. That the
        # validator refuses these combinations at construction is covered in
        # test_settings_secrets.py.
        production = settings.model_copy(
            update={"app_env": "production", "expose_error_details": False}
        )
        return TestClient(_app_with_failing_route(production), raise_server_exceptions=False)

    def test_an_unhandled_error_returns_a_generic_500(self, production_client: TestClient) -> None:
        response = production_client.get("/api/v1/_test/boom")

        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert response.json()["error"]["message"] == "An unexpected error occurred."

    def test_no_stack_trace_reaches_the_client(self, production_client: TestClient) -> None:
        response = production_client.get("/api/v1/_test/boom")

        body = response.text
        assert SECRET_IN_TRACEBACK not in body
        assert "RuntimeError" not in body
        assert "Traceback" not in body
        # File paths are their own disclosure.
        assert ".py" not in body

    def test_the_client_still_gets_a_correlation_id(self, production_client: TestClient) -> None:
        """Opaque to the client, but enough for support to find the traceback."""
        response = production_client.get("/api/v1/_test/boom")

        assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


class TestDevelopmentDiagnostics:
    def test_detail_is_available_when_explicitly_enabled(self, settings: Settings) -> None:
        """Local debugging should not require reading server logs."""
        local = settings.model_copy(update={"app_env": "local", "expose_error_details": True})
        client = TestClient(_app_with_failing_route(local), raise_server_exceptions=False)

        body = client.get("/api/v1/_test/boom").json()["error"]

        assert body["details"]["exception"] == "RuntimeError"
        assert SECRET_IN_TRACEBACK in body["details"]["detail"]

    def test_detail_is_withheld_by_default(self, settings: Settings) -> None:
        """Off unless asked for, even in development."""
        client = TestClient(_app_with_failing_route(settings), raise_server_exceptions=False)

        assert "details" not in client.get("/api/v1/_test/boom").json()["error"]


class TestErrorEnvelope:
    @pytest.fixture
    def client(self, settings: Settings) -> TestClient:
        return TestClient(_app_with_failing_route(settings), raise_server_exceptions=False)

    def test_application_errors_map_to_their_status(self, client: TestClient) -> None:
        response = client.get("/api/v1/_test/not-found")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert response.json()["error"]["message"] == "No such vendor."

    def test_details_are_included_when_supplied(self, client: TestClient) -> None:
        response = client.get("/api/v1/_test/conflict")

        assert response.status_code == 409
        assert response.json()["error"]["details"] == {"code": "ACME"}

    def test_a_routing_404_uses_the_same_envelope(self, client: TestClient) -> None:
        """One shape for every failure, including Starlette's own."""
        response = client.get("/api/v1/no-such-route")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_validation_failures_use_the_same_envelope(self, client: TestClient) -> None:
        response = client.post("/api/v1/auth/dev-token", json={})

        assert response.status_code == 422
        body = response.json()["error"]
        assert body["code"] == "validation_failed"
        assert body["details"]["fields"]

    def test_error_details_are_redacted(self, settings: Settings) -> None:
        """Details are developer-supplied, so they pass through redaction too."""
        application = create_app(settings)

        @application.get("/api/v1/_test/leaky")
        def leaky() -> None:
            raise ConflictError("nope", details={"api_key": "sk-live-should-not-appear"})

        client = TestClient(application, raise_server_exceptions=False)
        response = client.get("/api/v1/_test/leaky")

        assert "sk-live-should-not-appear" not in response.text
