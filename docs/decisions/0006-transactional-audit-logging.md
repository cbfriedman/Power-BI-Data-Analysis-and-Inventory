# 0006. Audit entries commit with the change they describe

- **Status:** Accepted
- **Date:** 2026-09-07

## Context

Milestone 1 requires that important data changes are recorded in audit logs. An
audit trail is only worth having if it is *complete* and *consistent*: an entry
describing a change that was rolled back is a lie, and a change with no entry is
a hole. Audit systems that write asynchronously, best-effort, or through a
logging sidecar drift from the data they claim to describe, and the drift is
invisible until someone needs the trail.

Approvals of product mappings are the highest-stakes case: they are permanent,
they drive automated matching forever after, and someone must be accountable for
each one.

## Decision

- One `audit_log` table, written through one service.
- The audit write **participates in the same database transaction** as the change
  it describes. Both commit or neither does.
- Every entry records: UTC timestamp, actor (user UUID, or `system` / `worker`),
  action, entity type, entity UUID, `before` and `after` JSONB limited to the
  changed fields, request correlation id, and IP where applicable.
- The table is **append-only**. No API exposes an update or delete path, and
  tests assert that attempts fail.
- Coverage is proven, not assumed: an integration test exercises every mutating
  endpoint and asserts a corresponding audit row (AC-12.1).
- Secrets, password hashes, and credentials are never written into an audit
  payload (AC-12.6).

At minimum, the following are audited: vendor and profile lifecycle; mapping
approval, rejection, and supersession; exception resolution; import batch
transitions; watchlist changes; and any administrative override of an automated
outcome.

## Alternatives considered

| Option | Why not |
|---|---|
| Application log lines | Not queryable as data, not transactional, and rotated away exactly when needed |
| Async queue or sidecar writer | Drifts from the data; a dropped message is an undetectable hole in the trail |
| PostgreSQL triggers | Captures column changes but not business intent, actor, or request context; harder to test and to evolve with Alembic |
| Temporal or history tables per entity | Heavier, and still lacks a single cross-entity trail for "who approved this mapping" |

## Consequences

**Positive** — the trail is complete by construction and impossible to
desynchronize from the data. Approvals are attributable. `request_id` ties an
HTTP request to its audit rows and its logs.

**Negative** — a write on the hot path of every mutation, and the table grows
quickly. Bulk operations must write audit rows in bulk rather than one per row,
or import performance suffers.

**Follow-ups** — partitioning or archival for `audit_log` if growth demands it;
revisit in phase 11 alongside the indexing review.
