"""Data access. Repositories own SQL and return plain data, never HTTP types.

Any repository touching an organization-owned table builds its statements
through :mod:`app.repositories.scoping` (ADR 0012).
"""
