# Phase 1 Status

Living document. It reflects **what is true**, not what is intended.
Last updated: 2026-09-07

---

## 1. Overall

| | |
|---|---|
| Milestone | 1 — Data foundation, ingestion, matching |
| Stage | **Phase 0 (scaffolding) complete. Phase 1 not started.** |
| Application code | Backend service skeleton + frontend shell. No business logic. |
| Database schema | None. No business tables, no migrations. |
| Backend tests | 21, all passing |
| Quality gates | 8 of 8 passing locally (§4) |
| Docker stack | **Unverified on this machine** — see §6, issue S1 |
| Blocking questions open | 7 (see §7) |

The stack builds and the API runs. Nothing yet reads a vendor file, calls
Nineyard, matches a product, or writes an audit row.

---

## 2. Phase tracker

Phases are defined in [architecture.md §6](architecture.md#6-implementation-order).

| # | Phase | Status | Notes |
|---|---|---|---|
| — | Planning and documentation | ✅ Complete | Scope, architecture, criteria, 8 ADRs |
| 0 | Scaffolding | ✅ Complete | Backend, frontend, infra, quality gates |
| 1 | DB foundation + audit | ⬜ Not started | Next unblocked work |
| 2 | Vendor database | ⬜ Not started | |
| 3 | Nineyard integration + sync | 🚫 Blocked | Blocked by B1 — no API specification |
| 4 | Import profiles | ⬜ Not started | Shape depends on B3 |
| 5 | File ingestion + raw retention | ⬜ Not started | Destination depends on B5 |
| 6 | Parsing + validation + reporting | ⬜ Not started | Needs sample files (B4) |
| 7 | Matching engine | ⬜ Not started | Rules fully specified; buildable now |
| 8 | Exception workflow | ⬜ Not started | Needs B2 for actor identity |
| 9 | Inventory, availability, watchlist | ⬜ Not started | |
| 10 | Admin interface | ⬜ Not started | Shell exists; screens are placeholders |
| 11 | Hardening | ⬜ Not started | |

Legend: ✅ complete · 🟨 in progress · ⬜ not started · 🚫 blocked

---

## 3. What phase 0 delivered

### Backend (`backend/`)

* FastAPI application factory with a lifespan that does **not** connect to the
  database at startup — a brief PostgreSQL outage must not stop the API booting.
* `GET /health` — liveness. Touches no dependency, so a database outage cannot
  cause an orchestrator to kill a healthy container.
* `GET /api/v1/health` — readiness. Reaches PostgreSQL and returns **503
  `degraded`** when it cannot (AC-0.5).
* Layer separation: `api`, `core`, `db`, `models`, `schemas`, `repositories`,
  `services`, `integrations`, `imports`, `tests`. Dependency directions are
  documented in [architecture.md §2](architecture.md).
* Typed settings from environment variables only, one `Settings` object.
* Structured JSON logging (structlog) with a `request_id` bound per request,
  echoed in `X-Request-ID`, and applied to uvicorn's own logs too.
* SQLAlchemy 2 declarative base with an explicit constraint naming convention
  (AC-1.6). Lazy engine, one session per request.
* Alembic wired to read `DATABASE_URL` from the environment. **No migrations
  yet** — business tables are phase 1.
* Ruff, mypy (strict), pytest configured; `warnings` are errors.

### Frontend (`frontend/`)

Next.js 15 / React 19 / TypeScript app shell with sidebar navigation, a live API
status indicator that verifies the environment-based API URL, and placeholder
screens for all nine admin areas. ESLint flat config, strict `tsconfig`.

### Infrastructure

`infra/docker-compose.yml` (postgres 16 + api + web), health checks on all three
services, named volume `prms_pgdata`, backend and frontend Dockerfiles running as
non-root, `.env.example` with placeholders only, comprehensive `.gitignore`,
`Makefile` and `tasks.ps1` task runners, and a README with exact startup steps.

`storage/raw`, `storage/processed`, and `storage/rejected` exist and are
bind-mounted into the API container. Directory structure is tracked; contents are
git-ignored, since retained vendor files are business data and may contain
commercially sensitive pricing (ADR 0004).

### Deliberately absent

No business tables, no Nineyard client, no matching, no imports, no audit rows,
no authentication. `models/`, `integrations/`, and `imports/` are empty packages
whose docstrings record the rules that will govern them.

---

## 4. Quality gate results

Run on 2026-09-07, Windows 11, Python 3.12.10, Node 24.19.0.

| Gate | Command | Result |
|---|---|---|
| Backend format | `ruff format .` | ✅ 34 files unchanged |
| Backend lint | `ruff check .` | ✅ All checks passed |
| Backend types | `mypy` (strict) | ✅ No issues in 33 source files |
| Backend tests | `pytest` | ✅ 21 passed |
| Frontend lint | `npm run lint` | ✅ Clean |
| Frontend types | `npm run typecheck` | ✅ Clean |
| Frontend build | `npm run build` | ✅ 9 routes prerendered |
| Compose config | `docker compose config` | ✅ Valid (client-side) |

An additional live smoke test against a real uvicorn process confirmed
`/health` → 200 with `X-Request-ID`, `/api/v1/health` → 503 `degraded` with
PostgreSQL absent, and correct CORS handling from a configured origin.

### Two real defects the gates caught

Both were found by tests rather than by inspection, and both would have reached
production.

* **`CORS_ALLOW_ORIGINS` crashed startup.** pydantic-settings JSON-decodes
  `list[str]` fields *before* validators run, so the plain value
  `http://localhost:3000` — exactly what `.env.example` and Compose supply —
  raised `JSONDecodeError` on boot. Fixed with `Annotated[list[str], NoDecode]`.
* **An unversioned route escaped `/api/v1`.** `swagger_ui_oauth2_redirect_url`
  does not follow `docs_url`, so `/docs/oauth2-redirect` was mounted at the root,
  violating CLAUDE.md §4. Fixed by setting it explicitly.

The route-contract test that should have caught the second one was itself broken:
FastAPI 0.141 nests included routers behind a private `_IncludedRouter` that
exposes no `routes` attribute, so walking `app.routes` silently found nothing and
the assertion passed vacuously. It now enumerates the OpenAPI schema — the actual
public contract — and asserts the set is non-empty first.

---

## 5. Toolchain changes made to this machine

| Change | Detail | Reversible |
|---|---|---|
| Python 3.12.10 installed | `winget install Python.Python.3.12 --scope user` | `winget uninstall Python.Python.3.12` |
| Docker Desktop launched | Started; engine did not come up (§6, S1) | Quit the app |

Neither existed beforehand: there was no Python at all, only the Microsoft Store
alias stub.

---

## 6. Open setup issues

### S1 — Docker cannot run on this machine *(blocks running the stack)*

`docker compose up` has **not** been executed. The Compose file validates, both
Dockerfiles are written, but the engine cannot start:

```
WSL2 is unable to start since virtualization is not enabled on this machine.
Please ensure the "Virtual Machine Platform" optional component is enabled and
virtualization is turned on in your computer's firmware settings.
```

Diagnostics: `HypervisorPresent: False`, `VirtualizationFirmwareEnabled: True`,
WSL distro `docker-desktop` is `Stopped`. The CPU's virtualization appears
enabled in firmware, so the likely cause is the missing Windows optional
component. Confirming that requires elevation, which this session does not have.

Fix (elevated PowerShell, then **reboot**):

```powershell
wsl.exe --install --no-distribution
```

If it still fails after the reboot, enable virtualization (Intel VT-x / AMD-V)
in the BIOS/UEFI.

Until then the Docker images are unbuilt and unverified, and the following are
unproven: image builds, container health checks, service dependency ordering,
the named volume, and Alembic running inside the container. Everything else in
§4 was verified natively.

---

## 7. Blocking questions

Unchanged from planning, with B7 promoted to a numbered question. B1 and B2 gate
implementation work; the rest shape it.

### B1 — Nineyard API specification *(blocks phase 3 entirely)*
API documentation and base URL; authentication model and how credentials are
issued; sandbox availability; rate limits; pagination style; a sample catalog
item payload identifying the exact **Catalog Item Number** field; whether delta
sync (`updated_since`) is supported; and whether the API exposes UPC/GTIN and
Amazon SKU/ASIN.

### B2 — Users, roles, and authentication *(blocks phases 8 and 10)*
Who reviews exceptions and approves mappings? Is local email/password (A6)
acceptable, or is there an existing identity provider? Audit attribution and
approval gating both depend on the answer.

### B3 — Pack size and unit-of-measure policy *(shapes phases 4, 6, 9)*
Normalize vendor quantities to the catalog unit at import, or store as stated
and defer conversion? This changes the import profile schema, so settling it
before phase 4 avoids a migration. Recommendation: store as stated plus pack
size, and defer — Milestone 1 makes no purchasing decisions.

### B4 — Representative vendor files *(blocks realistic phases 6 and 7)*
3–5 real vendor files (CSV and XLSX, anonymized), ideally one known-messy
example, plus typical and maximum row counts and file cadence.

### B5 — Raw file storage destination and retention *(blocks phase 5 deployment)*
Local disk, S3, Azure Blob, or other? Any retention, deletion, or compliance
requirement? Development uses the bind-mounted `storage/` directory regardless.

### B6 — Repository naming and stakeholder expectations
The repository is named `Power-BI-Data-Analysis-and-Inventory`, but Power BI is
explicitly out of scope for Milestone 1. Does anyone expect a Power BI
deliverable in this phase?

### B7 — Amazon SKU data source
With SP-API excluded, where do Amazon SKUs come from — manual entry, a
spreadsheet import, or the Nineyard catalog? If none, match priority 4 has no
data to operate on. Acceptable, but it should be a deliberate decision.

---

## 8. Assumptions

Adopted to keep work moving. Each is reversible; each is a place where being
wrong costs rework. A1–A14 are unchanged from planning; A15–A17 are new to
phase 0.

| # | Assumption | If wrong |
|---|---|---|
| A1 | Nineyard exposes an HTTP/JSON API with token or key authentication, catalog listing with pagination, and a stable Catalog Item Number per item. | Phase 3 is redesigned; the anti-corruption layer limits damage to `integrations/nineyard/`. |
| A2 | Nineyard is the sole source of canonical product records. An unmatched vendor line becomes an exception, never a new product. | The exception workflow gains a "create product" path and the identity rules need revision. |
| A3 | Vendor files are supplied manually (upload). No SFTP polling, email ingestion, or vendor API pulls. | Phase 5 grows an ingestion-source abstraction. |
| A4 | A vendor may have several import profiles, but one file maps to exactly one profile chosen at upload. | Profile auto-detection is added, raising risk R3. |
| A5 | Vendor files carry at minimum a vendor SKU and a quantity or availability indicator, usually a UPC and description. | Matching signal is weaker than planned; expect a much larger exception queue (R4). |
| A6 | Local email + password with three roles (admin, reviewer, viewer). No SSO in Milestone 1. | Swap behind `core/security.py`; audit attribution unaffected. |
| A7 | Raw file retention is indefinite for Milestone 1. | A retention job is added; storage sizing changes. |
| A8 | Single-tenant: one organization, one Nineyard account, one catalog. | Tenant scoping must be added to every table and query — expensive if deferred. |
| A9 | Single currency per vendor. Currency is recorded, never converted. | FX handling added later; the column already exists. |
| A10 | The OOS watchlist is user-curated, not auto-populated from stock levels. | The watchlist gains rule-based auto-population. |
| A11 | Availability transitions are evaluated per vendor, not aggregated across vendors. | An aggregate product-level view is added in phase 9. |
| A12 | In-app display of availability events is sufficient. No email/SMS/webhook. | A notification channel is added; out of scope today. |
| A13 | Deployment target is Linux containers; Windows is the development environment only. | Dockerfiles and CI matrix change. |
| A14 | Amazon SKUs arrive by manual entry or file import, since SP-API is excluded. | Match priority 4 stays dormant until a data source exists (B7). |
| A15 | Local-filesystem storage under `storage/` is sufficient for Milestone 1; the S3 backend is deferred until B5 is answered. | Add the S3 `StorageBackend` implementation; the protocol already isolates the choice. |
| A16 | A single API process is enough for now. The dedicated worker (`app/worker.py`) arrives with phase 5, when imports need to outlive a request. | Nothing built so far needs to change. |
| A17 | Next.js 15 with the App Router, React 19, and server components by default; client components only where interactivity requires them. | Localised to the frontend. |

---

## 9. Recommended next step

Phase 1 — database foundation and audit logging — is unblocked and is the
correct next move: `app_user`, `audit_log`, the transactional audit writer, the
first Alembic migration, and the AC-1.x schema-invariant tests (UUID keys, no
naive timestamp columns, no foreign key targeting a business key).

Resolving S1 is required before the Docker path can be trusted, but it does not
block phase 1 development if a PostgreSQL instance is available another way.
