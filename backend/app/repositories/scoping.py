"""Tenant scoping — the one place a tenant filter is applied.

Every organization-owned table carries ``organization_id`` (ADR 0009), but a
column enforces nothing by itself: a repository that forgets the ``WHERE`` is
a cross-tenant leak, and nothing in the schema would notice. Row-level
security is deferred until the first multi-tenant deployment (ADR 0012), so
until then this module is the rule.

The rule is short enough to review by eye: a repository never builds a bare
``select(Model)``, ``update(Model)`` or ``delete(Model)`` on a scoped model.
It asks a :class:`TenantScope` for one, and the scope appends
``WHERE model.organization_id = :organization_id`` before handing it back.
There is no ORM event, no session hook, and no global state — a reader can see
the filter being added in :meth:`TenantScope.apply` and nowhere else.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import Delete, Select, Update, delete, select, update
from sqlalchemy.orm import Session

from app.models.mixins import OrganizationScopedMixin

StatementT = TypeVar("StatementT", Select[Any], Update, Delete)


class TenantScopingError(TypeError):
    """A statement was requested for something that cannot be tenant-scoped."""


def require_scoped_model(model: type) -> type[OrganizationScopedMixin]:
    """Return ``model`` if it carries ``organization_id``; raise otherwise.

    ``organizations`` itself is the one table that is not scoped — it *is* the
    tenant — so asking for a scoped statement on it is a programming error,
    not a query.
    """
    if not (isinstance(model, type) and issubclass(model, OrganizationScopedMixin)):
        raise TenantScopingError(
            f"{model!r} is not organization-scoped; only models that include "
            "OrganizationScopedMixin can be queried through a TenantScope"
        )
    return model


@dataclass(frozen=True, slots=True)
class TenantScope:
    """The tenant a unit of work is acting for.

    Immutable, so a scope cannot be widened after it is handed to a repository.
    ``organization_id`` is required and must be a real UUID: a ``None`` would
    compile to ``organization_id IS NULL``, which matches nothing and fails
    silently — exactly the kind of mistake this module exists to make loud.
    """

    organization_id: uuid.UUID

    def __post_init__(self) -> None:
        if not isinstance(self.organization_id, uuid.UUID):
            raise TenantScopingError(
                f"organization_id must be a uuid.UUID, got {type(self.organization_id).__name__}"
            )

    def apply(self, statement: StatementT, model: type) -> StatementT:
        """Append the tenant filter to a statement that targets ``model``.

        This is the only line in the codebase that writes the filter. Every
        other method here delegates to it.
        """
        scoped = require_scoped_model(model)
        return statement.where(scoped.organization_id == self.organization_id)

    def select(self, model: type, *entities: Any) -> Select[Any]:
        """``SELECT ... FROM model WHERE model.organization_id = :id``.

        Pass ``entities`` to select specific columns instead of whole rows;
        the filter is applied to ``model`` regardless.
        """
        statement = select(*entities) if entities else select(model)
        return self.apply(statement, model)

    def update(self, model: type) -> Update:
        """``UPDATE model ... WHERE model.organization_id = :id``."""
        return self.apply(update(model), model)

    def delete(self, model: type) -> Delete:
        """``DELETE FROM model WHERE model.organization_id = :id``."""
        return self.apply(delete(model), model)


class ScopedRepository:
    """Base class for repositories that read or write organization-owned rows.

    Subclasses take the session and the tenant at construction and build every
    statement through ``self.scope``. A repository that needs a statement the
    scope cannot build is either querying ``organizations`` — which has its
    own, unscoped repository — or is about to write a leak.
    """

    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.scope = TenantScope(organization_id)

    def select(self, model: type, *entities: Any) -> Select[Any]:
        return self.scope.select(model, *entities)

    def update(self, model: type) -> Update:
        return self.scope.update(model)

    def delete(self, model: type) -> Delete:
        return self.scope.delete(model)
