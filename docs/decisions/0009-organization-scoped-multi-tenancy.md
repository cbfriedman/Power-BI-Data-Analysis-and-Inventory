# 0009. Organization-scoped multi-tenancy from the first migration

- **Status:** Accepted
- **Date:** 2026-09-08
- **Supersedes:** assumption A8 in [phase1-status.md](../phase1-status.md)

## Context

Planning recorded assumption A8: single-tenant — one organization, one Nineyard
account, one catalog. It also recorded what being wrong would cost: *"Tenant
scoping must be added to every table and every query — expensive if deferred."*

The Milestone 1 schema brief requires an `organizations` table and an
`organization_id` on every organization-owned table, so A8 no longer holds.

The timing matters more than the decision. Adding a tenant column later means a
migration touching every table, a backfill, a new unique-constraint shape on
every business key, and an audit of every existing query for a missing filter —
with a silent cross-tenant data leak as the failure mode if one is missed. Doing
it before any row exists costs one column per table.

## Decision

- `organizations` is the tenant root, keyed by an immutable UUID with a unique
  `slug` as its business key.
- Every other table carries `organization_id`, `NOT NULL`, indexed, referencing
  `organizations.id` with `ON DELETE RESTRICT`.
- Uniqueness on business keys is scoped **per tenant**, not globally: a catalog
  item number, vendor code, UPC, or user email is unique within an organization
  and may legitimately recur in another.
- `RESTRICT` rather than `CASCADE` on the tenant reference. Deleting an
  organization with data is refused; removing a tenant is an explicit, ordered
  operation, not an unreviewed cascade that silently erases a customer.
- A test enumerates the live schema and fails if any table lacks
  `organization_id`, so the rule cannot decay as tables are added.

## Alternatives considered

| Option | Why not |
|---|---|
| Stay single-tenant, add scoping later | The expensive path A8 already identified. Backfilling a tenant key across 21 tables with live data, and re-scoping every unique constraint, is a migration nobody wants to write. |
| Schema-per-tenant | Migrations must run N times and stay in lockstep; cross-tenant reporting becomes painful. Disproportionate at this scale. |
| Database-per-tenant | Strongest isolation, heaviest operations. Not warranted by any stated requirement. |
| `CASCADE` on the tenant FK | One mistaken `DELETE FROM organizations` erases a customer's entire history, audit trail included. |

## Consequences

**Positive** — tenant isolation is structural. Business keys are correctly
scoped from the start. The cost is one indexed column per table.

**Negative** — every query must filter by `organization_id`, and a forgotten
filter is a cross-tenant leak that the schema alone cannot prevent. Row-level
security or a session-scoped query guard should be evaluated before the first
real multi-tenant deployment; Milestone 1 relies on repository-layer discipline
and tests.

**Follow-ups** — decide whether PostgreSQL row-level security is warranted;
seed a default organization for single-tenant installs so the extra concept
stays invisible to users who do not need it.
