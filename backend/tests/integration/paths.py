"""Filesystem locations the database tests need.

Kept in its own module so the paths are importable from ``conftest`` without a
circular import, and resolved from ``__file__`` so the suite works no matter
which directory pytest was invoked from.
"""

from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
