# 0007. Isolate Nineyard behind an anti-corruption layer

- **Status:** Accepted
- **Date:** 2026-09-07

## Context

Nineyard is an external system this project does not control, and — as of this
planning step — one whose API is not yet specified to us (blocking question B1,
risk R1). Its field names, response shapes, pagination style, and error semantics
can change without our involvement.

If Nineyard's payload shapes are used directly as domain models, every upstream
change becomes a schema migration and a refactor across the codebase, and the
domain model ends up describing Nineyard's internal concerns rather than this
system's.

## Decision

- All Nineyard access lives in `app/services/nineyard/`.
- Responses are parsed into explicit Pydantic DTOs (`NineyardCatalogItemDTO` and
  peers) and then **translated** into domain models by a mapper in that package.
- **No Nineyard field name appears in `app/models/`** (AC-2.5). The domain speaks
  in `product`, `product_identifier`, and `amazon_sku`.
- Credentials come from environment variables only and are never logged, not even
  at DEBUG level.
- Retries use exponential backoff with jitter on 429 and 5xx, honoring
  `Retry-After`, with a configured maximum.
- Every raw item payload is persisted to `nineyard_item_payload` with a checksum,
  so a sync can be replayed and diffed without calling the API again.
- Until real API documentation and a sandbox credential exist, the client is
  developed against a recorded-fixture double, and phase 3 is marked blocked
  rather than guessed at.

## Alternatives considered

| Option | Why not |
|---|---|
| Use Nineyard payload shapes as domain models | Every upstream rename becomes a migration; the domain inherits an external system's design |
| Generate models from an OpenAPI spec and use them directly | Same coupling, and no specification is available anyway |
| Call Nineyard from route handlers as needed | Scatters credentials, retry logic, and payload knowledge across the codebase |

## Consequences

**Positive** — an upstream change is contained to one package and one mapper.
The domain model reflects this system's needs. Retained payloads make syncs
replayable and diffable offline, which also makes the fixture double realistic.

**Negative** — an extra translation layer to write and keep in step, and DTOs
that partly duplicate domain fields. This is the intended cost; it is small
relative to R1.

**Follow-ups** — B1 must be answered before phase 3 can be built or estimated.
When the real specification arrives, revisit pagination, delta-sync support, and
whether UPC and Amazon SKU data actually originate here (B7).
