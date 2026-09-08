"""Health endpoint behaviour (AC-0.5)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.core.middleware import REQUEST_ID_HEADER


def test_liveness_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "prms-api-test"


def test_liveness_does_not_touch_the_database(degraded_client: TestClient) -> None:
    """Liveness must stay green while the database is down.

    Otherwise an orchestrator kills and restarts a healthy process during a
    database outage, which helps nobody.
    """
    response = degraded_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_liveness_timestamp_is_utc_aware(client: TestClient) -> None:
    checked_at = datetime.fromisoformat(client.get("/health").json()["checked_at"])

    assert checked_at.tzinfo is not None
    assert checked_at.utcoffset() == UTC.utcoffset(None)


def test_readiness_reports_ok_when_database_reachable(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"
    assert body["api_version"] == "v1"
    assert body["dependencies"] == [{"name": "postgresql", "status": "ok", "detail": None}]


def test_readiness_reports_503_when_database_unreachable(degraded_client: TestClient) -> None:
    response = degraded_client.get("/api/v1/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"][0]["status"] == "unavailable"


def test_request_id_is_echoed_back(client: TestClient) -> None:
    response = client.get("/health", headers={REQUEST_ID_HEADER: "test-correlation-id"})

    assert response.headers[REQUEST_ID_HEADER] == "test-correlation-id"


def test_request_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get("/health")

    assert response.headers.get(REQUEST_ID_HEADER)
