"""SQLAlchemy ORM models.

Empty by design at scaffold stage. Business tables arrive in phase 1 (DB
foundation + audit) and must follow the conventions in ``app.db.base``:
an immutable UUID primary key, UTC ``TIMESTAMPTZ`` columns, and business keys
as separate uniquely constrained attributes rather than foreign-key targets
(ADR 0002).
"""
