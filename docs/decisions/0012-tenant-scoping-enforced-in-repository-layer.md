# 0012. Enforce tenant scoping in the repository layer until row-level security

- **Status:** Accepted
- **Date:** 2026-09-14
- **Deciders:** Implementation lead
- **Supersedes / Superseded by:** none. Refines assumption A19 in
  [phase1-status.md](../phase1-status.md).
- **Relates to:** [ADR 0009](0009-organization-scoped-multi-tenancy.md)

## Context

Every organization-owned table carries `organization_id` (ADR 0009), and a
schema test proves it. But a column enforces nothing by itself. The database
will happily answer `SELECT * FROM vendors WHERE code = 'ACME'` with rows from
every tenant, and `vendors` is unique on `(organization_id, code)` — so two
tenants using the same vendor code is not an edge case, it is the normal
shape of the data. A repository that forgets one `WHERE` clause is a
cross-tenant leak, and nothing in the schema would notice.

Assumption A19 admitted this: "tenant isolation relies on repository-layer
discipline plus tests. PostgreSQL row-level security is not enabled." That
was written when no repository existed. Phase 2 (vendor CRUD) and the Amazon
ingestion (ADR 0011) are about to create the first ones, and the cheapest
moment to fix a habit is before anyone has formed the wrong one.

Two facts about row-level security (RLS) shape the timing:

- RLS is the correct long-term answer. It makes the *database* refuse to
  return another tenant's rows, regardless of what the application asks for.
- RLS needs a per-request session variable (`SET LOCAL app.organization_id`)
  wired through the connection lifecycle, policies on every table in the
  migration, and a way to run migrations and administrative jobs *outside*
  the policies. That is real work with its own failure modes, and there is
  currently one tenant. Building it now would be building for a deployment
  that does not exist yet.

## Decision

**Interim rule.** Every repository that reads or writes an organization-owned
table builds its statements through `app.repositories.scoping`:

- `TenantScope(organization_id)` is an immutable value holding the tenant a
  unit of work acts for. Its `select(Model)`, `update(Model)` and
  `delete(Model)` return the corresponding SQLAlchemy statement with
  `WHERE Model.organization_id = :organization_id` already appended, and
  `apply(statement, Model)` adds the same clause to a statement the caller
  built. That `where` is written in exactly one place — `TenantScope.apply` —
  and nowhere else.
- `ScopedRepository(session, organization_id)` is the base class future
  repositories inherit. It exposes the three builders and holds the scope.
- The scope refuses two things at construction or call time, loudly:
  a model that does not include `OrganizationScopedMixin` (asking for a
  scoped `organizations` query is a bug, not a query), and an
  `organization_id` that is not a `uuid.UUID` — because `None` would compile
  to `IS NULL`, match nothing, and fail silently.

**What it is not.** There is no ORM event, no session hook, no query
interception, and no global "current tenant". A reviewer reading a repository
can see the scope being used or not being used. That is the point: the rule
is meant to be checked by eye in code review and by test, not enforced by
machinery that could itself hide a bypass.

**Tests fix the rule in place.** A unit test enumerates every mapped class
that includes `OrganizationScopedMixin` from the ORM registry, asserts that
set is every table except `organizations`, and proves from compiled SQL that
each of select, update and delete carries the filter for each model — 60
assertions today, growing automatically with the schema. An integration test
creates two organizations with a vendor of the same code in each and proves
the helper returns, updates and deletes only the caller's tenant, including
when the caller supplies the other tenant's primary key.

**Row-level security is deferred** until the first deployment that serves
more than one organization. At that point RLS is added *in addition to* this
helper, not instead of it: the helper keeps queries correct and cheap, RLS
makes the database refuse to be wrong.

## Alternatives considered

| Option | Why not |
|---|---|
| Enable PostgreSQL row-level security now | Correct eventually, premature today. It needs per-request `SET LOCAL`, policies on 20 tables, a bypass role for migrations and jobs, and tests for all of it — for a system with one tenant. It is the follow-up, not the first step. |
| A SQLAlchemy `do_orm_execute` event that injects the filter globally | Invisible in the repository code, so a reviewer cannot tell whether a query is scoped by reading it. Bypassable by Core statements and raw SQL without any signal. Hides the very mistake it is meant to catch. |
| A `with_loader_criteria` on every scoped model | Same objection: magic that a reader cannot see, plus a global "current tenant" that has to be set correctly on every entry point, which is exactly the forgotten-line failure mode restated. |
| Rely on code review alone | Assumption A19 as written. Review catches most things; the one it misses is a leak. |
| Put `organization_id` on every method signature by convention only | Nothing checks it. The helper *is* that convention, made mandatory by construction. |

## Consequences

**Positive** — a leak now requires bypassing a helper on purpose, which is
visible in a diff, rather than forgetting a clause, which is not. The first
repositories are written the right way from day one. The test set grows with
the schema without anyone remembering to extend it.

**Negative / cost** — one more import and one more argument on every
repository. A repository that legitimately needs cross-tenant access (a
platform-admin report, a tenant-migration job) has to build its statement
without the scope and say so in a comment; that friction is intended. The
helper does not cover raw SQL (`text(...)`), which is why raw SQL against
organization-owned tables is reserved for migrations and tests.

**Follow-ups**

- Assumption A19 in phase1-status.md is amended to cite this record.
- When phase 2 lands, its vendor repository inherits `ScopedRepository` and
  is the first real consumer; any friction found there is fed back here.
- Before the first multi-tenant deployment: an ADR for row-level security
  covering the session variable, the policies, the bypass role, and how
  Alembic runs. Enabling RLS is a schema change and ships as a migration.
