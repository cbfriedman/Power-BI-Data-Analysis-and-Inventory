"""Transaction utilities.

ADR 0006 requires an audit row to commit or roll back with the change it
describes. That is only achievable if there is one obvious way to express "these
writes succeed together or not at all" — which is what these helpers are.

Nothing here is clever; the value is that every mutation uses the same construct,
so a reviewer can see the boundary rather than infer it from where ``commit()``
happens to be called.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.session import get_session_factory

_logger = get_logger(__name__)


@contextmanager
def transaction(session: Session) -> Iterator[Session]:
    """Commit on clean exit, roll back on any exception.

    The exception is always re-raised: this controls the transaction, it does
    not swallow failures.

        with transaction(session):
            vendor.is_active = False
            audit.record(session, action="vendor.deactivated", ...)

    Both writes land, or neither does.
    """
    try:
        yield session
    except Exception:
        session.rollback()
        _logger.warning("transaction.rolled_back", exc_info=True)
        raise
    else:
        session.commit()


@contextmanager
def savepoint(session: Session) -> Iterator[Session]:
    """A nested transaction that can fail without losing the outer one.

    For work that is allowed to fail individually inside a larger unit — one bad
    row in an import batch, say, where the batch should continue. On failure the
    savepoint alone is rolled back and the enclosing transaction stays usable.
    """
    nested = session.begin_nested()
    try:
        yield session
    except Exception:
        # Unconditional. A failed flush leaves the nested transaction *inactive*,
        # and rolling it back is precisely how the session is made usable again —
        # guarding on is_active here skips the recovery and the enclosing
        # transaction dies with a PendingRollbackError instead.
        nested.rollback()
        raise
    else:
        nested.commit()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Open a session, run a transaction in it, and close it.

    For code with no request behind it — the worker, scheduled jobs, CLI
    commands. Inside a request, take the session from the ``get_db`` dependency
    and use :func:`transaction` instead, so the whole request shares one unit of
    work.
    """
    session = get_session_factory()()
    try:
        with transaction(session):
            yield session
    finally:
        session.close()


def run_in_transaction[T](work: Callable[[Session], T]) -> T:
    """Run ``work`` in its own session and transaction, returning its result."""
    with session_scope() as session:
        return work(session)
