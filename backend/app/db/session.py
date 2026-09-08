"""Database engine and session management.

Synchronous SQLAlchemy 2 with psycopg 3, per ADR 0008. The engine is created
lazily so importing the application never opens a connection — which is what
lets the unit tests run without a database.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide engine.

    ``create_engine`` does not connect; the first connection is opened on first
    use. ``pool_pre_ping`` discards connections the database has closed
    underneath us, which is the common failure after a container restart.
    """
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide session factory."""
    return sessionmaker(
        bind=get_engine(),
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding one session per request.

    One unit of work per request (ADR 0008). The session is always closed; the
    caller decides whether to commit.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
