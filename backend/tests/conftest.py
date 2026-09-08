"""Shared pytest fixtures.

The scaffold's tests run without a database. The ``get_db`` dependency is
overridden with a stub session so route behaviour — including the degraded path
— is testable in isolation. Tests that need real PostgreSQL are marked
``integration`` and arrive with the schema in phase 1.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import create_app


class StubSession:
    """Minimal stand-in for a SQLAlchemy ``Session``.

    Only ``execute`` is exercised by the health repository. ``fails`` makes it
    raise the same error class a genuinely unreachable database would.
    """

    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails
        self.executed: list[Any] = []

    def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if self.fails:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        self.executed.append(statement)
        return None

    def close(self) -> None:
        return None


@pytest.fixture
def settings() -> Settings:
    """Deterministic settings for tests, independent of the developer's .env."""
    return Settings(
        app_env="test",
        app_name="prms-api-test",
        log_level="WARNING",
        log_format="json",
        database_url=SecretStr("postgresql+psycopg://test:test@localhost:5432/test"),
        auth_jwt_secret=SecretStr("unit-test-signing-key-not-used-anywhere-for-real"),
        dev_auth_enabled=True,
        cors_allow_origins=["http://localhost:3000"],
    )


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    """An application instance wired to the test settings."""
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def healthy_db_app(app: FastAPI) -> FastAPI:
    """App whose database dependency answers successfully."""
    app.dependency_overrides[get_db] = lambda: StubSession(fails=False)
    return app


@pytest.fixture
def unavailable_db_app(app: FastAPI) -> FastAPI:
    """App whose database dependency raises as an unreachable database would."""
    app.dependency_overrides[get_db] = lambda: StubSession(fails=True)
    return app


@pytest.fixture
def client(healthy_db_app: FastAPI) -> Iterator[TestClient]:
    """Test client against a healthy application."""
    with TestClient(healthy_db_app) as test_client:
        yield test_client


@pytest.fixture
def degraded_client(unavailable_db_app: FastAPI) -> Iterator[TestClient]:
    """Test client against an application whose database is unreachable."""
    with TestClient(unavailable_db_app) as test_client:
        yield test_client
