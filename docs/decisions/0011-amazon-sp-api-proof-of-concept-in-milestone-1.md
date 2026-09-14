# 0011. Admit a read-only Amazon SP-API ingestion into Milestone 1

- **Status:** Accepted
- **Date:** 2026-09-14
- **Deciders:** Client (project owner) by request; implementation lead by
  acceptance of the bounded scope below
- **Supersedes / Superseded by:** none. Narrows the "Amazon SP-API" exclusion
  in CLAUDE.md §3 and [milestone-1-scope.md §3](../milestone-1-scope.md).
- **Relates to:** [ADR 0002](0002-product-identity-uuid-and-catalog-item-number.md),
  [ADR 0003](0003-deterministic-match-priority-chain.md),
  [ADR 0007](0007-nineyard-anti-corruption-layer.md),
  [ADR 0010](0010-identifier-model-and-mapping-placement.md)

## Context

The client has made a working Amazon proof of concept the condition for
continuing the project. The request, verbatim:

> Before moving forward, I would like the first technical milestone to include
> a working proof of concept with our actual Amazon account that demonstrates:
> SP-API/LWA authentication; retrieval of the sales data required for
> 7/14/30-day velocity; retrieval of relevant inventory and inbound inventory;
> mapping Amazon SKUs to our Nineyard Catalog Item #/UPC structure; storage of
> the data in PostgreSQL; scheduled data ingestion; basic error handling and
> logging.

Two binding rules are in tension. CLAUDE.md §3 lists Amazon SP-API as
explicitly out of Milestone 1: "Do not build, stub, scaffold, or add
dependencies for" it. CLAUDE.md §7 says that when something in §3 seems
necessary, "stop and ask", and that any architecturally significant choice
gets an ADR. This record is that ADR. Silently widening the scope is not an
option; neither is refusing a request the project's continuation depends on.

Facts that shape the decision:

- Everything the client asks for is a **read**. Nothing in the request requires
  writing to Amazon, touching buyer data, or computing a purchasing decision.
- The schema already has a home for Amazon listings. `marketplace_listings`
  holds one row per seller SKU with `asin` and `marketplace_id` (ADR 0010), and
  open question **B7** asks where those rows come from. SP-API listings are an
  answer.
- "Mapping Amazon SKUs to our Nineyard Catalog Item #/UPC structure" is a
  product-matching problem, and product matching is already governed by the
  priority chain in CLAUDE.md §5.1 and ADR 0003. The POC gains nothing by
  inventing a second matching path, and CLAUDE.md §5.2 forbids one.
- SP-API authentication is Login with Amazon (LWA) only: a refresh token is
  exchanged for a short-lived access token. AWS SigV4 request signing is no
  longer required for SP-API calls. This keeps the credential surface to a
  client id, a client secret, and a refresh token.
- A recurring job needs a scheduler. The repository has none, and
  [milestone-1-scope.md §3](../milestone-1-scope.md) already allows "a job
  runner sufficient to trigger catalog sync and process imports".

## Decision

A **bounded, read-only Amazon SP-API ingestion** is added to Milestone 1 scope
as item 14. It consists of exactly the following, and nothing else:

| # | Capability | Bound |
|---|---|---|
| 1 | LWA authentication | Refresh-token → access-token exchange; credentials from environment variables only, typed `SecretStr` |
| 2 | Order-line retrieval | Enough to compute 7/14/30-day sales velocity per seller SKU: order id, purchase date, order status, seller SKU, ASIN, quantity ordered/shipped. **No buyer fields.** |
| 3 | FBA inventory retrieval | Fulfillable quantity plus the inbound quantities (working / shipped / receiving) per seller SKU |
| 4 | FBM quantity retrieval | Merchant-fulfilled available quantity per seller SKU |
| 5 | Listings retrieval | Seller SKU, ASIN, marketplace, product title and identifiers (UPC/EAN where Amazon exposes them) — enough to map to `products` |
| 6 | Storage in PostgreSQL | New tables under the existing conventions: UUID keys, `organization_id`, UTC `TIMESTAMPTZ`, Alembic migration, raw payload retained per item as with Nineyard |
| 7 | Scheduled ingestion | A scheduler that runs the ingestion on an interval and on demand, recording each run with counts and outcome |
| 8 | Error handling and logging | The existing error envelope, redaction, correlation ids and audit conventions; retries on 429/5xx only, honouring rate-limit headers |
| 9 | One read-only velocity endpoint | `GET /api/v1/amazon/velocity` (name provisional) returning 7/14/30-day units per seller SKU |
| 10 | One CLI | Runs one ingestion cycle in the foreground, for verification without the scheduler |

**Mapping obeys the existing rules.** An Amazon seller SKU is mapped to a
product only through the priority chain of ADR 0003: automatically at priority
1 (normalized UPC) or priority 2 (Catalog Item Number), or at priority 4 once a
human has approved the listing's mapping. A listing that resolves to no product,
or to more than one, enters `product_mapping_exceptions` exactly as a vendor
row would. No listing is ever mapped on title similarity. This means the POC's
"mapping" is the existing matching engine applied to `marketplace_listings`,
and it is one more reason phase 7 must exist before the mapping half of the
POC can be shown end to end.

**Anti-corruption layer.** As with Nineyard (ADR 0007), no SP-API field name
appears in `app/models/`. The library's response types stop at
`app/integrations/amazon/`.

**Still explicitly OUT** of Milestone 1, unchanged by this record:

- Replenishment quantities, reorder points, or coverage math of any kind
- Profitability, fees, or landed-cost calculations
- ConnectBooks
- **Any write to Amazon** — no feeds, no listing updates, no price or quantity
  pushes, no order acknowledgements
- **Buyer PII** and anything requiring a Restricted Data Token: no buyer name,
  email, address, or phone. The ingestion never requests an RDT.
- Walmart
- Power BI

The retrieval *mechanism* per capability (direct API call vs. an SP-API report)
is an implementation choice for the POC, not fixed here; what is fixed is the
data retrieved and the read-only bound.

## Alternatives considered

| Option | Why not |
|---|---|
| Refuse the change and hold the documented scope | The client has made the POC a condition of continuing. Holding the line on a scope document at the cost of the project serves nobody; the honest response is to admit a bounded version and record it. |
| Build the POC in a separate throwaway repository | Throws away the settings, secrets handling, redaction, error envelope, audit writer, migration discipline, and `marketplace_listings` that already exist, and produces a demo that cannot become the product. The POC is more convincing *inside* the foundation than beside it. |
| Full SP-API integration including replenishment suggestions | Replenishment math is the core of a later milestone and depends on vendor cost and lead-time data Milestone 1 has not ingested. It would also convert a read-only demonstration into a decision-making system before the data under it is trustworthy. |
| Hand-roll the SP-API client on `httpx` | Feasible now that SigV4 is gone, but LWA token refresh, per-endpoint rate-limit handling, report polling and the endpoint catalogue are exactly the boilerplate a maintained library already carries. `python-amazon-sp-api` (MIT) is adopted; the ACL keeps it replaceable. |
| Celery or RQ for scheduling | Both need a broker (Redis) — a new piece of infrastructure to host, configure and back up for one recurring job. APScheduler 3.x runs in-process with no broker. Its constraint — it must run in exactly one process — is acceptable and is documented below. |
| Reuse `nineyard_sync_runs` for Amazon runs | The columns fit, but the table is named and audited as a Nineyard concept. A separate run table keeps the two source systems independently queryable and avoids a `source_system` discriminator on a table that never needed one. |

## Consequences

**Positive** — the project continues, on terms that keep every rule in CLAUDE.md
§4–§6 intact. Open question **B7** gains a concrete answer for FBA/FBM sellers:
`marketplace_listings` is populated from SP-API listings. The matching engine
gets a second real input alongside vendor files, which is a better test of it
than vendor files alone. Sales velocity is the first piece of demand data the
later replenishment milestone will need, arriving early and already audited.

**Negative / cost**

- **New tables** — provisionally `amazon_ingestion_runs`, `amazon_orders`,
  `amazon_order_lines`, `amazon_inventory_snapshots`, and raw-payload retention
  for each; listings land in the existing `marketplace_listings`. Final names
  and columns are settled in the migration and
  [database-schema.md](../database-schema.md), not here.
- **New dependency:** `python-amazon-sp-api` (MIT). It pulls in its own HTTP
  stack; the ACL is the containment boundary.
- **New dependency:** `APScheduler` 3.x (MIT). It must run in **one** process —
  a dedicated worker, never inside each uvicorn replica, or every replica
  ingests on its own timer. [architecture.md](../architecture.md) plans a
  `worker` process for phase 5; the scheduler brings that process forward,
  and `infra/docker-compose.yml` gains the service when it does.
- **New configuration**, all environment-only and `SecretStr` where secret:
  LWA client id and secret, refresh token, seller id, marketplace id(s), region
  endpoint, ingestion interval. The production start-up validator refuses to
  boot with any of them missing when ingestion is enabled.
- **Rate limits.** The Orders API endpoints are among the most tightly
  throttled in SP-API. A first full backfill of 30 days of order lines may take
  a long time; incremental runs afterwards are cheap. The run table records
  throttling so the cost is visible, not guessed.
- **Milestone 1 grows.** Phases 2–11 are unchanged in content and order, but
  the POC precedes them ([phase1-status.md §10](../phase1-status.md)).

**Follow-ups**

- CLAUDE.md §2 gains item 14 and §3 narrows its Amazon bullet (done with this
  record). [milestone-1-scope.md](../milestone-1-scope.md) is updated the same
  way.
- [acceptance-criteria.md](../acceptance-criteria.md) needs an **AC-14** group
  covering each of the ten capabilities above, including negative tests: no
  write endpoint is ever called (asserted by a mocked transport that fails on
  any non-GET), no buyer field is ever stored, and a listing with no UPC and no
  Catalog Item Number ends in the exception queue rather than mapped.
- A new blocking question, **B8**: the client must register an SP-API
  application (or authorise an existing one) and supply the LWA credentials
  and seller/marketplace ids through environment variables. Nothing can be
  demonstrated against the real account until then, and nothing in this
  repository will ever contain those values.
- `docs/security.md` gains a section on the Amazon credential set and the
  redaction patterns for LWA tokens.
- Revisit this record if the client asks for any write to Amazon, for buyer
  data, or for replenishment suggestions. Each is a new ADR, not an amendment
  to this one.
