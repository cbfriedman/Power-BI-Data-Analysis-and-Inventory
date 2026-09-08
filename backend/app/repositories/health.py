"""Health-check data access.

The only repository that exists at scaffold stage. Repositories own SQL and
return plain data; they never build HTTP responses.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def ping(session: Session) -> None:
    """Execute the cheapest possible round trip to the database.

    Raises ``sqlalchemy.exc.SQLAlchemyError`` if the database is unreachable.
    Callers decide how to present that.
    """
    session.execute(text("SELECT 1"))
