# Phase 1 Status

Living document. It reflects **what is true**, not what is intended.
Last updated: 2026-09-15 (read-only Amazon SP-API client — POC step 2)

---

## 1. Overall

| | |
|---|---|
| Milestone | 1 — Data foundation, ingestion, matching |
| Stage | **Phase 1 complete; phase 3 diagnostic built.** Schema, audit service, configuration/security foundation, and a read-only Nineyard probe exist. Backend is deployed to Railway. |
| Application code | Schema, audit service, auth foundation, error handling, redaction, read-only Nineyard client + CLI probe, tenant scoping helper for repositories (ADR 0012), Amazon SP-API configuration and a read-only SP-API client behind an anti-corruption layer (nothing calls it yet). No vendor/import/matching logic. |
| Database schema | 21 tables, 21 enum types, 113 indexes, 61 check constraints, 73 foreign keys, 1 append-only trigger |
| Migrations | 1 revision, applied and reversed against PostgreSQL 16.15 |
| Backend tests | **468 passed** (`pytest`: 355 unit + 113 integration). `git grep -c "def test_"` finds 339 functions (225 unit, 114 integration — one of which is the `test_database_url` fixture helper in `conftest.py`); the difference is parametrisation. |
| Quality gates | 8 of 8 passing locally **and in GitHub Actions** (§4), 2026-09-14 |
| Docker stack | **Verified in CI** — full `docker compose up --build` from `.env.example`, API healthy against PostgreSQL, migration applied and checked, web answering (§4, §6 S1). Backend also live on Railway (§6 S2). |
| Blocking questions open | 8 (see §7); B1 partially answered, B2 narrowed, B7 partially answered by ADR 0011, B8 new |

The schema, the audit writer, the security foundation, and a read-only Nineyard
diagnostic exist and are verified. Nothing yet reads a vendor file, synchronises
Nineyard data, or matches a product.

---

## 2. Phase tracker

Phases are defined in [architecture.md §6](architecture.md#6-implementation-order).

| # | Phase | Status | Notes |
|---|---|---|---|
| — | Planning and documentation | ✅ Complete | Scope, architecture, criteria, 10 ADRs |
| 0 | Scaffolding | ✅ Complete | Backend, frontend, infra, quality gates, GitHub Actions CI (2026-09-14) |
| 1 | DB foundation + audit | ✅ Complete | Schema, migration, transactional audit writer, transaction utilities, config/security foundation |
| A | Amazon SP-API read-only ingestion ([ADR 0011](decisions/0011-amazon-sp-api-proof-of-concept-in-milestone-1.md)) | 🟨 Client built, not yet used | Precedes phase 2 by client request (§10). **Exists:** typed settings, redaction rules, and `app/integrations/amazon/` — a read-only client over `python-amazon-sp-api` with five operations, typed DTOs, a five-class error taxonomy and a retry policy ([amazon-integration.md](amazon-integration.md)), tested against fakes only. **Does not exist:** tables, ingestion service, scheduler, endpoint, CLI. Nothing has run against the real account (B8). |
| 2 | Vendor database | ⬜ Not started | Tables exist; no API or CRUD. `require_roles(DATA_OPERATOR)` is ready to guard it. |
| 3 | Nineyard integration + sync | 🟨 Diagnostic only | **Exists:** read-only client (`app/integrations/nineyard/client.py`, `errors.py`, `sanitize.py`), probe (`app/integrations/nineyard/probe.py`), and CLI (`app/cli/nineyard_probe.py`), tested by `tests/unit/test_nineyard_client.py`, `test_nineyard_probe.py`, `test_nineyard_cli.py` (mocked; no live calls). The public OpenAPI spec has been analysed ([nineyard-field-mapping.md](nineyard-field-mapping.md)). **Does not exist:** any sync service — nothing writes Nineyard data to `products`, `product_identifiers`, `marketplace_listings`, `nineyard_sync_runs`, or `nineyard_item_payloads`. The probe has not been run against the live API. See [nineyard-integration.md](nineyard-integration.md) and B1. |
| 4 | Import profiles | ⬜ Not started | `vendor_import_profiles` exists; shape of the JSONB rules still depends on B3/B4 |
| 5 | File ingestion + raw retention | ⬜ Not started | `import_files` exists; no `StorageBackend` yet |
| 6 | Parsing + validation + reporting | ⬜ Not started | Needs sample files (B4) |
| 7 | Matching engine | ⬜ Not started | Schema supports the full priority chain; engine unwritten |
| 8 | Exception workflow | ⬜ Not started | `product_mapping_exceptions` exists; `Principal` now supplies actor identity, so no longer blocked by B2 |
| 9 | Inventory, availability, watchlist | ⬜ Not started | All four tables exist; no diffing logic |
| 10 | Admin interface | ⬜ Not started | Shell exists; screens are placeholders. Needs a sign-in flow once B2 settles. |
| 11 | Hardening | ⬜ Not started | |

Legend: ✅ complete · 🟨 in progress · ⬜ not started · 🚫 blocked

---

## 3. What phase 1 delivered

### Schema

21 tables covering tenancy and identity, catalog and identifiers, vendors and
import profiles, ingestion, inventory history, matching exceptions, the OOS
watchlist, source-system retention, and audit.

Full documentation, including the Mermaid ER diagram, the relationship and
delete-behaviour reference, and index coverage, is in
[docs/database-schema.md](database-schema.md).

The parts that carry the most weight:

* **Identity.** `products.id` is an immutable UUID and the only foreign-key
  target; `catalog_item_number` is a unique business attribute. Every FK in the
  database points at a UUID — asserted by a test, not by review.
* **Identifiers.** `product_identifiers` is one lookup surface for all identifier
  types, with vendor and marketplace context enforced by a check constraint, and
  three partial unique indexes giving each kind its correct scope. A UPC resolves
  to exactly one product per tenant, which is what makes match priority 1
  unambiguous rather than "pick the first row".
* **Multiple Amazon SKUs.** One row per SKU in `marketplace_listings`. Never a
  delimited column.
* **Approved mappings.** Priorities 3 and 4 read `mapping_status = 'APPROVED'` on
  `vendor_products` and `marketplace_listings`, each requiring an approver and a
  timestamp by check constraint ([ADR 0010](decisions/0010-identifier-model-and-mapping-placement.md)).
* **Import idempotency.** `import_files.sha256` is unique per tenant; a partial
  unique index permits only one non-failed `import_jobs` row per file, so a
  successful import is never silently repeated while a failed one can be retried.
* **Inventory history is append-only.** Snapshots are keyed
  `(import_job_id, vendor_product_id)` and every outbound FK is `RESTRICT`, so
  history cannot be deleted from underneath.
* **No repeated alerts.** `availability_events` is unique on
  (`current_snapshot_id`, `event_type`) — one snapshot raises a given transition
  exactly once.
* **The watchlist is buying intent.** `desired_quantity`, `max_unit_cost`,
  `priority`, and `reason` describe what the company wants to purchase, not
  everything that happens to be at zero stock.
* **Audit is append-only in the database.** A trigger rejects `UPDATE` and
  `DELETE` on `audit_events`, including from a direct psql session.

### Configuration and security foundation

Full detail in [docs/security.md](security.md). In brief:

* **Secrets are typed.** `DATABASE_URL`, `AUTH_JWT_SECRET` and
  `NINEYARD_PASSWORD` are `SecretStr`, so they cannot be printed by accident.
  Reading a real value takes an explicit `.get_secret_value()`, which keeps
  every such use greppable and at a genuine boundary.
* **Production refuses development defaults.** The shipped signing key, the dev
  token endpoint, and error-detail exposure each prevent start-up when
  `APP_ENV=production`. A signing key under 32 characters is refused everywhere.
* **Log redaction at the sink.** Key-based masking plus pattern matching for
  bearer tokens, bare JWTs, DSN passwords, and inline `api_key=` assignments —
  applied on both the structlog path and the stdlib path used by third-party
  libraries. The same functions clean audit payloads.
* **Correlation ids** flow from middleware through a context variable into log
  lines, audit rows, and error responses.
* **One error envelope** for application errors, Starlette's own errors,
  validation failures, and unhandled exceptions. **No stack trace ever reaches a
  client in production.**
* **Audit writer** (ADR 0006): adds the row to the caller's session and does not
  commit, so a change and its audit entry share one transaction.
* **Transaction utilities**: `transaction()`, `savepoint()`, `session_scope()`.
* **Replaceable authentication.** A development JWT backend behind an
  `AuthenticationBackend` protocol, with four roles — `ADMIN`,
  `PURCHASING_MANAGER`, `DATA_OPERATOR`, `VIEWER`. Authorization always reads
  the database, never token claims, so a revocation applies on the next request.
* **`.gitignore` hardened** against token caches, credential files, and imported
  client data — verified by running `git check-ignore`, not by inspection.

### Migration

One revision, `506fd0ecc33a`. Beyond the autogenerated tables it enables
`pg_trgm`, creates the trigram search indexes, installs the audit trigger, and —
critically — drops the 21 enum types on downgrade. PostgreSQL leaves enum types
behind when their tables are dropped, so a downgrade that forgets them makes the
*next* upgrade fail with "type already exists", a defect that would only appear
in a real deployment. A test asserts the round trip.

### Tenant scoping helper (2026-09-14, ADR 0012)

`app/repositories/scoping.py` is the interim rule for tenant isolation until
row-level security is introduced. `TenantScope(organization_id)` builds
`select`/`update`/`delete` statements with
`WHERE Model.organization_id = :id` already applied — the clause is written in
one method and nowhere else — and `ScopedRepository` is the base class every
future repository inherits. It refuses a model without
`OrganizationScopedMixin` and refuses a non-UUID tenant id, because `None`
would compile to `IS NULL` and match nothing silently.

`tests/unit/test_tenant_scoping.py` enumerates every scoped model from the ORM
registry (20 today — every table except `organizations`, asserted), and proves
from compiled SQL that all three statement kinds carry the filter for each.
`tests/integration/test_tenant_scoping.py` creates two organizations with a
vendor of the **same code** in each — which the per-organization unique index
permits, and which is exactly the shape of a leak — and proves select, update
and delete stay inside the caller's tenant, including a lookup by the other
tenant's primary key. Assumption A19 is amended accordingly.

### Amazon SP-API client — the anti-corruption layer (2026-09-15, POC step 2)

`app/integrations/amazon/` wraps `python-amazon-sp-api` 2.1.23 (MIT, now a
dependency) the way `app/integrations/nineyard/` wraps Nineyard (ADR 0007).
Full description in [amazon-integration.md](amazon-integration.md). The
points that matter most:

* **Read-only by structure.** `AmazonClient` has exactly five public
  methods — `request_report`, `get_report_status`,
  `download_report_document`, `fetch_report`, `iter_inventory_summaries` —
  and no generic call method. A test asserts the set and a second asserts no
  write-shaped name (`create_`, `put_`, `post_`, `update_`, `delete_`,
  `submit_`) exists other than `request_report`.
* **One credential boundary.** The library's `{refresh_token, lwa_app_id,
  lwa_client_secret}` dict is built in one private method from `SecretStr`
  values and passed straight to the library constructor; it is not stored,
  logged or returned. A test drives a request through the real logging
  pipeline at `DEBUG`, adds the library's own logger output, and asserts no
  secret reaches the output.
* **Two library behaviours closed off**, found by reading the installed
  code rather than its README: `SP_API_DEFAULT_MARKETPLACE` in the
  environment silently overrides an explicitly passed marketplace (the
  client refuses to construct while it is set), and the library will look for
  credentials in its own env vars and config files if not given a dict (it
  always is).
* **Retries** only on the library's 429 / 500 / 503 / 504 exceptions, capped
  exponential backoff with jitter, `Retry-After` honoured, attempts from
  `AMAZON_MAX_ATTEMPTS`; LWA failures are never retried. A throttled
  inventory page is re-requested with the same `nextToken`.
* **50 unit tests** against fakes of the library classes: credential
  boundary, each DTO from a realistic payload, three-page pagination,
  retry-then-succeed, exhaustion into `AmazonRateLimited` /
  `AmazonTransientError`, auth not retried, `fetch_report` reaching `DONE`,
  `CANCELLED`, `FATAL` and timeout.

Not yet verified against the real account: the application's SP-API roles,
report latency, real throttling, and the report charset — listed in the
doc's §7.

### Amazon SP-API configuration and secret handling (2026-09-15, POC step 1)

The first slice of the ADR 0011 work, done before credentials arrive so that
nothing about their handling is improvised later:

* **Settings** (`app/core/config.py`): `amazon_enabled`, `amazon_lwa_client_id`,
  `amazon_lwa_client_secret` and `amazon_lwa_refresh_token` (both `SecretStr`),
  `amazon_seller_id`, `amazon_marketplace_id` (default `ATVPDKIKX0DER`),
  `amazon_region` (validated to `NA`/`EU`/`FE`), `amazon_timeout_seconds`,
  `amazon_max_attempts`. `amazon_configured` is true only when all four
  credentials are present and non-blank. With `AMAZON_ENABLED=true` and any of
  them missing, start-up is refused in **every** environment with a message
  naming exactly the missing variables — the same fail-fast style as the
  production guards.
* **Redaction** (`app/core/redaction.py`): `refresh_token`, `client_secret`,
  `lwa_*` and `x-amz-access-token` are masked by key. Two value patterns were
  added, and one of them closed a real gap: the existing inline rule caught
  `access_token=...` but **not** the JSON form `"access_token": "..."` — the
  closing quote after the key broke the match — so a raw LWA token-endpoint
  body logged by an HTTP library would have passed through intact. JSON
  members named `access_token`, `refresh_token`, `client_secret`, `id_token`,
  `api_key`, `password`, `secret` or `authorization` are now masked, and so is
  the bare LWA token shape (`Atza|…` access, `Atzr|…` refresh) wherever it
  appears.
* **Tests:** 39 new unit cases across `test_config.py`, `test_settings_secrets.py`
  and `test_redaction.py`, including that `repr(settings)`, `safe_dump()` and a
  real structlog line never contain the secret values, and the end-to-end
  pipeline masks the SP-API header, the token body and a token in free text.
* `.env.example` documents the variables with the Seller Central path
  (Apps & Services > Develop Apps, self-authorised private app). No real value
  exists anywhere in the repository.

Still owed from the ADR 0011 follow-ups: an AC-14 group in
[acceptance-criteria.md](acceptance-criteria.md) and an Amazon section in
[security.md](security.md).

### Deliberately absent

No Nineyard *synchronisation* (the client is read-only and diagnostic), no
file parsing, no matching engine, and no vendor or import endpoints. No password storage, MFA, refresh tokens, or rate limiting —
Entra ID will own credentials, and building a half-credential store first would
be work thrown away ([security.md §8](security.md) lists this honestly).

---

## 4. Quality gate results

Run on 2026-09-14 via `.	asks.ps1 check`. Windows 11, Python 3.12.10, Node 24.19.0, PostgreSQL 16.15.
The same gates run in GitHub Actions on every push
([`.github/workflows/ci.yml`](../.github/workflows/ci.yml), described in
[deployment.md](deployment.md#continuous-integration)). First run, all three
jobs green on the first attempt with no change to any Dockerfile or the Compose
file: https://github.com/cbfriedman/Power-BI-Data-Analysis-and-Inventory/actions/runs/34892991973.

| CI job | Result |
|---|---|
| `backend` (Ubuntu, Python 3.12, `postgres:16-alpine` service) | ✅ 83 files formatted · ruff clean · mypy clean (81 files) · **`302 passed in 5.63s`**, 0 skipped — the integration suite ran against the service container |
| `frontend` (Ubuntu, Node 24) | ✅ `npm ci`, eslint, tsc, `next build` |
| `compose-smoke` (Ubuntu, Docker) | ✅ all three images built; `/api/v1/health` → 200 with `postgresql: ok` 2 s after start; `alembic upgrade head` applied `506fd0ecc33a`; `alembic check` → "No new upgrade operations detected"; web answered on :3000; `down -v` clean. 93 s end to end. |

| Gate | Command | Result |
|---|---|---|
| Backend format | `ruff format .` | ✅ 91 files unchanged |
| Backend lint | `ruff check .` | ✅ All checks passed |
| Backend types | `mypy` (strict) | ✅ No issues in 89 source files |
| Backend tests | `pytest` | ✅ `468 passed in 7.52s` — `tests/unit`: `355 passed`; `tests/integration`: `113 passed` |
| Migration apply | `alembic upgrade head` | ✅ Applied to PostgreSQL 16.15 |
| Migration reverse | `alembic downgrade base` → `upgrade head` | ✅ Clean round trip, 0 residual enum types |
| Migration drift | `alembic check` | ✅ No new upgrade operations detected |
| Frontend lint | `npm run lint` | ✅ Clean |
| Frontend types | `npm run typecheck` | ✅ Clean |
| Frontend build | `npm run build` | ✅ 10 routes prerendered (12 static pages) |
| Compose config | `docker compose config` | ✅ Valid (client-side) |

### A design conflict the tests caught

`audit_events.actor_user_id` was written as `ON DELETE SET NULL`, the obvious
choice for "keep the audit entry, forget the user". It is wrong: `SET NULL` makes
PostgreSQL issue an `UPDATE` against `audit_events` during the delete, which the
append-only trigger correctly refuses — so deleting a user failed with a
confusing trigger error rather than a clear constraint error.

Changed to `RESTRICT`, which states the actual rule: a user who has acted cannot
be deleted, only deactivated. That is consistent with every other entity in this
schema, and it makes the audit trail genuinely immutable. Two tests now cover it
— the delete is refused, and deactivation leaves the trail attributable.

Nothing found this by inspection. It surfaced because the relationship tests
issue Core deletes and let the database decide.

### Repository hygiene (2026-09-14)

`README.md` had been committed as **UTF-16 LE without a BOM**, so Git stored it
as a binary blob and GitHub rendered it as garbage. It was decoded and rewritten
as UTF-8 without BOM; the decoded text was verified character-for-character
identical to the original (6,755 characters, 209 lines) before the write.

A scan of all 148 tracked files found no other non-UTF-8 file and no UTF-8 BOM.
Every committed blob already used LF; CRLF appeared only in the working copy
via `core.autocrlf`. A root `.gitattributes` now pins `* text=auto eol=lf` and
`*.ps1 text eol=crlf` so neither problem depends on a contributor's machine
again. `git add --renormalize .` changed nothing but `README.md`.

The README's "No migrations exist yet" sentence was also corrected: revision
`506fd0ecc33a` exists.

### Three more the security tests caught

* **Routes read the wrong settings.** Route dependencies called `get_settings()`
  directly, which returns the process-wide cache — so an app built by
  `create_app(settings)` could answer according to a *different* configuration.
  Harmless in production where they coincide; wrong in tests, and a real hazard
  for any multi-configuration process. Routes now take settings off
  `app.state` via `get_app_settings`, which makes disagreement impossible.
* **`X-Forwarded-For` could 500 a request.** The header is caller-supplied text
  and was written straight into an `INET` column, so `X-Forwarded-For: nonsense`
  would fail the INSERT and turn an ordinary request into a 500 — trivially
  triggerable from outside. The value is now parsed with `ipaddress` at the
  boundary and discarded if it is not a real address.
* **`savepoint()` skipped its own recovery.** It guarded the rollback on
  `nested.is_active`, but a failed flush leaves the nested transaction
  *inactive* — precisely when the rollback is needed. The enclosing transaction
  then died with `PendingRollbackError`. The guard is gone.

---

## 5. Toolchain changes made to this machine

| Change | Detail | Reversible |
|---|---|---|
| Python 3.12.10 installed | `winget install Python.Python.3.12 --scope user` (2026-09-07) | `winget uninstall` |
| **PostgreSQL 16.15 installed** | `winget install PostgreSQL.PostgreSQL.16`, service `postgresql-x64-16`, port 5432 | `winget uninstall` |
| Role and databases created | Role `prms` (LOGIN, CREATEDB); databases `prms` and `prms_test` | `DROP DATABASE` / `DROP ROLE` |
| Docker Desktop launched | Engine still fails to start (§6, S1) | Quit the app |

PostgreSQL was installed natively because the Docker container cannot run on
this machine. It matches the `postgres:16-alpine` image the Compose file uses,
so the schema is verified against the same major version that will run in
deployment.

Two local configuration changes accompanied it:

* `.env` now points `DATABASE_URL` at `localhost` rather than the `postgres`
  Compose service name. `.env.example` is unchanged and still documents both.
* `app/core/config.py` resolves `.env` from absolute paths (repository root and
  `backend/`). Previously a relative `.env` was read from the working directory,
  so running anything from `backend/` silently missed the file and fell back to
  defaults — a footgun that would have bitten every developer.

---

## 6. Open setup issues

### S1 — Docker is intermittent on this machine *(no longer blocks anything)*

**The Compose stack is verified in CI** (§4): the `compose-smoke` job builds
all three images from a clean checkout, starts them from `.env.example`,
confirms the API reports PostgreSQL healthy, applies and checks the migration
inside the `api` container, and confirms the web container answers. That is
Milestone 1 exit criterion #1, and it passed on the first run with no change
to any Dockerfile or the Compose file. The frontend image, which could never
be built on this machine, built cleanly there.

What remains true locally: the engine is unreliable here. It ran on
2026-09-08 long enough to build the **backend** image, but the **frontend**
image fails in `npm ci` with `ECONNRESET` because of a Docker networking fault
on this machine — see [deployment.md](deployment.md). The original failure
mode was:

```
WSL2 is unable to start since virtualization is not enabled on this machine.
Please ensure the "Virtual Machine Platform" optional component is enabled and
virtualization is turned on in your computer's firmware settings.
```

Diagnostics: `HypervisorPresent: False`, `VirtualizationFirmwareEnabled: True`,
WSL distro `docker-desktop` is `Stopped`.

Fix (elevated PowerShell, then **reboot**):

```powershell
wsl.exe --install --no-distribution
```

**What this does and does not block.** Nothing, now. Local Docker is a
convenience; CI is the proof. Anyone changing a Dockerfile or the Compose file
should expect the `compose-smoke` job to be the arbiter.

### S2 — Deployment state (Railway)

The **backend** service is deployed and healthy: `GET /api/v1/health` returns
`{"status":"ok","environment":"production","dependencies":[{"name":"postgresql","status":"ok"}]}`
against Railway's managed PostgreSQL. Still to do, in order: set
`alembic upgrade head` as the backend pre-deploy command; create the
`frontend` service (Root Directory `frontend`, `NEXT_PUBLIC_API_BASE_URL` set
**before** the first build); set backend `CORS_ALLOW_ORIGINS` to the frontend
origin. The first Railway frontend build is the real test of the frontend
image. There is **no authentication in production yet** — see
[deployment.md](deployment.md) before any mutation endpoint ships.

---

## 7. Blocking questions

Unchanged. B1 and B2 gate implementation work; the rest shape it. B3 and B4 have
become more pressing now that `vendor_import_profiles` exists and its JSONB rule
columns need real shapes.

### B1 — Nineyard API specification *(partially answered)*

**Answered:** the base URL, the authentication endpoint
(`POST /api/OAuth/UsernameToken`), its request body (`email`, `password`,
`companyId`), the bearer-token scheme, and four read-only endpoint groups —
`/api/Items`, `/api/Skus`, `/api/Vendors`, `/api/PurchaseOrders`.

The `nineyard_api_key` setting has been removed accordingly: the real
authentication is a credential triple, not an API key.

**Still unknown, and now answerable by running the probe rather than by asking:**
response envelope shape, field names and types, nullability, paging mechanism and
parameter names, rate limits, and which groups the integration account can
actually read. `docs/nineyard-field-mapping.md` tracks each one.

**Still needs a person at Nineyard**, because no single probe run can establish
it:

1. Which field is the **Catalog Item Number**, and is it stable across syncs?
   The whole product-identity model rests on this.
2. What is the relationship between Items and Skus? It decides how three tables
   are populated.
3. Is incremental sync supported (an `updatedSince` filter)? If not, full pulls
   are the only option and `nineyard_sync_runs.cursor` stays unused.
4. How are deletions represented — absence from the collection, or a flag?
   Getting this wrong silently deactivates live products.
5. Are there published rate limits?

### B2 — Users, roles, and authentication *(narrowed; now blocks only phase 10)*
**No longer blocks phase 8.** `Principal` supplies actor identity, the four
roles are defined and seeded, and `require_roles` is ready to guard mutation
endpoints, so the exception workflow can be built now.

Two decisions remain, both about Entra ID rather than about whether to use it:

1. **Is Entra authoritative for roles?** If yes, `user_roles` becomes a cache of
   Entra app roles and the local grant path is removed rather than left as a
   second source of truth. If no, Entra authenticates and this system authorizes.
2. **Provisioning:** just-in-time user creation on first sign-in (simplest), or
   SCIM (correct if deprovisioning must be prompt).

Confirmation that Entra ID is in fact the target would also be useful — see
assumption A21. Phase 10 needs a sign-in flow, which needs both answers.

### B3 — Pack size and unit-of-measure policy *(now shapes a built table)*
`vendor_import_profiles.pack_size_handling` is JSONB and currently empty.
Normalize vendor quantities to the catalog unit at import, or store as stated
and defer conversion? Recommendation unchanged: store as stated plus pack size,
and defer — Milestone 1 makes no purchasing decisions.

### B4 — Representative vendor files *(blocks realistic phases 6 and 7)*
3–5 real vendor files (CSV and XLSX, anonymized), ideally one known-messy
example, plus typical and maximum row counts and file cadence. These determine
the concrete shape of `column_map`, `normalization_rules`, and
`availability_rules`.

### B5 — Raw file storage destination and retention *(blocks phase 5 deployment)*
Local disk, S3, Azure Blob, or other? Any retention, deletion, or compliance
requirement? `import_files.storage_uri` is a plain string, so any backend fits.

### B6 — Repository naming and stakeholder expectations
The repository is named `Power-BI-Data-Analysis-and-Inventory`, but Power BI is
explicitly out of scope for Milestone 1.

### B7 — Amazon SKU data source *(partially answered by ADR 0011)*
[ADR 0011](decisions/0011-amazon-sp-api-proof-of-concept-in-milestone-1.md)
makes the read-only SP-API listings retrieval a source for
`marketplace_listings`. Still open: whether *every* Amazon SKU the client sells
is visible through that account and marketplace set, or whether some still
need import or manual entry.

### B8 — Amazon SP-API credentials *(new; blocks any live POC run)*
The client must register an SP-API application (or authorise an existing one)
and supply the LWA client id, client secret, refresh token, seller id, and
marketplace id(s) as environment variables on the machine or service that runs
the ingestion. Until then the POC can be built and tested only against mocked
responses. None of these values will ever be committed, logged, or printed.

---

## 8. Assumptions

A1–A17 carry forward from earlier phases, with these changes:

| # | Change |
|---|---|
| **A6** | **Superseded.** The roles are `ADMIN`, `PURCHASING_MANAGER`, `DATA_OPERATOR`, `VIEWER` — not admin/reviewer/viewer. There is no local password login: the development backend issues tokens without credentials, and Entra ID will own authentication ([security.md §4](security.md)). |
| **A8** | **Superseded.** Single-tenancy no longer holds: the schema is organization-scoped throughout ([ADR 0009](decisions/0009-organization-scoped-multi-tenancy.md)). |
| **A15** | Confirmed for now — `import_files.storage_uri` is backend-agnostic, so local filesystem today and S3 later needs no schema change. |
| **A18** *(new)* | Approved mappings live on the owning row rather than in a separate mapping table, so full mapping *history* is reconstructed from `audit_events`. If that becomes a common query, a dedicated history table is the follow-up ([ADR 0010](decisions/0010-identifier-model-and-mapping-placement.md)). |
| **A19** *(amended 2026-09-14)* | Tenant isolation is enforced in the repository layer by `app/repositories/scoping.py`, which every repository must use ([ADR 0012](decisions/0012-tenant-scoping-enforced-in-repository-layer.md)); unit and integration tests fix the rule in place. PostgreSQL row-level security remains **deferred** until the first multi-tenant deployment, when it is added in addition to the helper, not instead of it. |
| **A20** | `pg_trgm` is available in every target environment. It ships with PostgreSQL contrib and is present in both `postgres:16-alpine` and the EDB Windows build. |
| **A21** *(new)* | Microsoft Entra ID is the intended production identity provider. The `AuthenticationBackend` protocol is shaped for it; if a different provider is chosen, the protocol still holds but the JWKS/RS256 assumptions in `EntraIdAuthenticationBackend` would change. |
| **A22** *(new)* | The service sits behind a proxy that sets `X-Forwarded-For`. Exposed directly, that header is caller-supplied and the recorded client address is worth nothing (the value is validated, so a bad one is simply dropped). |

The full A1–A17 list is unchanged from the 2026-09-07 revision and remains in
force.

---

## 9. Recommended next step

> **Superseded by §10.** The order below is the Milestone 1 order, which now
> follows the Amazon proof of concept.

**Phase 2 — the vendor database.** It is fully unblocked and is the natural
first consumer of everything phase 1 built: CRUD under `/api/v1/vendors`, guarded
by `require_roles(RoleCode.DATA_OPERATOR)`, with each mutation wrapped in
`transaction()` alongside an `audit.record_change()` call. That exercises the
audit writer, the transaction utilities, the role guard, and the error envelope
against real endpoints, which is the honest test of whether the foundation is
usable rather than merely present.

Phase 4 (import profiles) follows, though its JSONB rule shapes still want real
vendor files (B4).

---

## 10. Re-planning (2026-09-14)

The client has requested an **Amazon SP-API proof of concept** as the first
technical milestone. This is a scope change — Amazon SP-API is listed as out of
Milestone 1 in [CLAUDE.md §3](../CLAUDE.md) and
[milestone-1-scope.md §3](milestone-1-scope.md) — and
[ADR 0011](decisions/0011-amazon-sp-api-proof-of-concept-in-milestone-1.md)
records it: exactly what the bounded, read-only ingestion includes, what stays
out (no writes to Amazon, no buyer PII, no replenishment math), and the new
tables, dependencies (`python-amazon-sp-api`, APScheduler 3.x), and
configuration it brings. CLAUDE.md §2 now lists it as item 14 and §3 narrows
the Amazon exclusion accordingly. The work order is now
**(a)** the Amazon POC, then **(b)** Milestone 1 phases 2 through 11 in the
order documented in [architecture.md §6](architecture.md#6-implementation-order).
Nothing already built is affected: phases 0, 1, and the phase 3 diagnostic stand
as delivered. The blocking questions in §7 remain open, B7 now has a partial
answer, and B8 (SP-API credentials) is new. Still to do before the POC starts:
an AC-14 group in [acceptance-criteria.md](acceptance-criteria.md) and a
credential section in [security.md](security.md), both listed as follow-ups in
the ADR.
