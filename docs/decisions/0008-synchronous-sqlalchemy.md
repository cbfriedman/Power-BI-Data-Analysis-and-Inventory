# 0008. Synchronous SQLAlchemy, and no pandas in the import path

- **Status:** Accepted
- **Date:** 2026-09-07

## Context

Two implementation choices sit underneath most of Milestone 1's backend work, and
both have a tempting default that is wrong for this system.

**Concurrency.** FastAPI is commonly written async-first. But this milestone is
dominated by bulk row processing and file parsing, not by fan-out to slow network
services. Async buys little here and introduces real hazards: a blocking call
accidentally left on the event loop stalls the whole process, async and sync
sessions bridge badly, and transaction boundaries become harder to reason about
and to test.

**Parsing.** pandas is the reflexive choice for reading CSV and XLSX. It is also
actively dangerous for this data. pandas infers dtypes, so `"012345678905"`
becomes a float, leading zeros vanish, and long identifiers acquire scientific
notation. That silently corrupts exactly the fields matching depends on — UPCs
and vendor SKUs — and it does so without raising anything (risk R2).

## Decision

**Concurrency**

- Use synchronous SQLAlchemy 2 ORM with psycopg 3.
- Declare FastAPI route handlers as plain `def`, so Starlette runs them in its
  threadpool.
- One unit of work per request. Import processing commits **per chunk** (default
  500 rows) so a large file makes forward progress and a failure leaves a
  resumable batch instead of losing hours of work.
- The worker claims batches with `SELECT ... FOR UPDATE SKIP LOCKED` and a lease,
  so no broker is required in Milestone 1.

**Parsing**

- **pandas is not used in the import path.**
- CSV is read with the stdlib `csv` module, every field as `str`, with no type
  inference. Encoding is detected with `charset-normalizer` and overridable per
  profile; the BOM is stripped.
- XLSX is read with `openpyxl` in `read_only=True` mode. Cell values are
  converted to `str` deterministically — integers without a trailing `.0`, dates
  as ISO-8601. Formula cells use cached values, and a profile flag decides
  whether a formula cell is an error.
- Typed coercion happens **after** extraction, per profile field rule, and the
  raw string is always retained alongside the parsed value.
- Fixture tests cover leading zeros, scientific notation, and UPCs stored as
  numbers in Excel.

## Alternatives considered

| Option | Why not |
|---|---|
| Async SQLAlchemy with asyncpg | No meaningful benefit for bulk row work; adds event-loop blocking hazards and async/sync bridging bugs |
| Mixed async API with sync workers | Two session styles, two sets of idioms, and two ways to get transactions wrong |
| pandas with `dtype=str` everywhere | Workable in principle, but one forgotten `dtype` silently corrupts identifiers; the dependency earns nothing once type inference is off |
| Celery or RQ for the worker | Adds a broker and its operational burden for a queue depth PostgreSQL handles fine at this scale |

## Consequences

**Positive** — straightforward, debuggable code and transaction boundaries. No
class of "blocked the event loop" bugs. Identifier fidelity is preserved by
construction rather than by remembering a keyword argument. One less
infrastructure component to run.

**Negative** — a threadpool caps concurrent request throughput, which is
irrelevant for an internal admin tool but would matter for a public API.
Streaming XLSX by hand is more code than `read_excel`. If Nineyard sync later
needs high-concurrency fan-out, that specific path may warrant `httpx.AsyncClient`
in isolation.

**Follow-ups** — revisit if a public high-concurrency API is added, or if
`openpyxl` proves too slow on real files, in which case evaluate
`python-calamine` (which does not do type inference either).
