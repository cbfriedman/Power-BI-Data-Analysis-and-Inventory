# Amazon SP-API Integration

Status: **Read-only client, tables, orders ingestion and inventory ingestion
built.** No scheduler, endpoint or CLI exist yet; the listings→product
mapping is not written. Everything has been exercised only against fakes —
nothing has run against the real seller account (blocking question **B8**).
Last updated: 2026-09-15

---

## 1. Why a wrapper, and why this shape

[ADR 0011](decisions/0011-amazon-sp-api-proof-of-concept-in-milestone-1.md)
admits a bounded, read-only SP-API ingestion into Milestone 1. The library
chosen to talk to Amazon, `python-amazon-sp-api` (MIT), exposes the whole
Selling Partner API — feeds, listings writes, pricing, orders, shipments,
several hundred operations — through a family of classes that share one
credential mechanism. Handing that library to application code would mean the
read-only bound rests on nobody ever calling the wrong method.

`app/integrations/amazon/` is the anti-corruption layer (ADR 0007, applied
here as it was to Nineyard). It wraps exactly the calls the POC needs, maps
every result into a frozen, typed DTO, translates the library's dozen
exception classes into five of our own, and owns the retry policy. Nothing
above it imports `sp_api`.

The library was inspected before the wrapper was written — signatures, the
credential provider, the response wrapper, the exception hierarchy — so the
calls below match what is installed (`python-amazon-sp-api` 2.1.23), not a
guess at it.

---

## 2. The boundary

### What the library needs, and where it gets it

The library authenticates with Login with Amazon: a long-lived **refresh
token** is exchanged for a short-lived access token, which it sends as the
`x-amz-access-token` header. It wants those credentials as a plain dict:

```python
{"refresh_token": ..., "lwa_app_id": ..., "lwa_client_secret": ...}
```

That dict is built in one private method, `AmazonClient._credentials()`,
from the `SecretStr` values on `AmazonConfig`, and passed straight to the
library constructor by `AmazonClient._api()`. It is not stored on the client,
not logged, and not returned by anything. A test asserts the library received
exactly those three keys and that no attribute of the client holds the plain
dict.

`AmazonConfig.from_settings(settings)` is the only way in. It refuses to build
if any of `AMAZON_LWA_CLIENT_ID`, `AMAZON_LWA_CLIENT_SECRET`,
`AMAZON_LWA_REFRESH_TOKEN` or `AMAZON_SELLER_ID` is missing, naming the
missing ones; resolves `AMAZON_MARKETPLACE_ID` to the library's marketplace
entry; and refuses a marketplace that is not served from `AMAZON_REGION` (a
UK marketplace id with `AMAZON_REGION=NA` would otherwise be sent to the
North American endpoint and fail with an opaque 400).

### Two things the library does that the wrapper closes off

- **Environment override.** `sp_api.base.Client.__init__` reads
  `SP_API_DEFAULT_MARKETPLACE` from the environment and lets it **override an
  explicitly passed marketplace**. `AmazonClient` refuses to construct while
  that variable is set, so the marketplace can only come from `Settings`.
- **Credential discovery.** Left to itself the library will look for
  credentials in its own environment variables and config files. The wrapper
  always passes the dict explicitly, so nothing outside `Settings` is
  consulted.

### Secrets in logs

The redaction rules in `app/core/redaction.py` (extended for this work) mask
`refresh_token`, `client_secret`, `lwa_*` and `x-amz-access-token` by key;
mask the JSON form `"access_token": "..."` that an HTTP library would log from
the token endpoint; and mask the bare LWA token shape (`Atza|…`, `Atzr|…`)
wherever it appears. The library's own loggers (`sp_api.*`) go through the
stdlib path, which is redacted too. A test drives a request through the real
logging pipeline at `DEBUG` and asserts no secret value reaches the output.

---

## 3. The public surface — five reads, nothing else

`AmazonClient` exposes exactly these methods. A test asserts the set, and a
second test asserts no public method name starts with `create_`, `put_`,
`post_`, `update_`, `delete_` or `submit_` (other than `request_report`).
There is no generic `call(method, path)`, no `request`, `get`, `post` — no
way to reach any other library endpoint through this object.

| Method | Returns | What it does |
|---|---|---|
| `request_report(report_type, data_start, data_end, report_options=None)` | `ReportRequest` | Asks Amazon to generate a report for the marketplace. The one non-GET call SP-API needs for a read; it creates a queued export and nothing else. `data_start`/`data_end` must be timezone-aware UTC. |
| `get_report_status(report_id)` | `ReportStatus` | Where the report is in Amazon's queue. |
| `download_report_document(report_document_id)` | `bytes` | The finished document. The library downloads it, gunzips it if Amazon compressed it, and decodes it using the charset Amazon declared; that text is returned as **UTF-8 bytes** so callers see one encoding. |
| `fetch_report(report_type, data_start, data_end, report_options=None, *, poll_interval_s=15, timeout_s=1800)` | `bytes` | Request → poll until terminal → download. Raises `AmazonReportFailed` on `CANCELLED`, `FATAL`, `DONE` without a document, or timeout. |
| `iter_inventory_summaries(*, details=True, page_delay_s=0.0)` | `Iterator[InventorySummary]` | Every FBA inventory summary for the marketplace, following `nextToken` until exhausted. `details=True` requests the `inventoryDetails` block, which is where the inbound quantities live. `page_delay_s` is slept *between* pages — the retry policy reacts to throttling; the delay avoids it. |

Report types are passed as strings (the library's `ReportType` enum values,
e.g. `GET_MERCHANT_LISTINGS_ALL_DATA`,
`GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE_GENERAL`,
`GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA`). Which reports the ingestion uses
is decided in the next step, not here.

---

## 4. The DTOs

All frozen dataclasses in `app/integrations/amazon/dtos.py`. Each has a
`from_payload` classmethod that names the SP-API field it reads, so the
mapping lives in one place and a renamed upstream field fails there, loudly.
No SP-API field name appears in `app/models/`.

| DTO | Fields | Source fields |
|---|---|---|
| `ReportRequest` | `report_id` | `createReport` → `reportId` |
| `ReportStatus` | `processing_status`, `report_document_id`; properties `is_terminal`, `is_done` | `getReport` → `processingStatus` (`IN_QUEUE` / `IN_PROGRESS` / `DONE` / `CANCELLED` / `FATAL`), `reportDocumentId` |
| `InventorySummary` | `seller_sku`, `asin`, `fnsku`, `condition`, `last_updated`, `total`, `fulfillable`, `inbound_working`, `inbound_shipped`, `inbound_receiving`, `reserved_total`, `unfulfillable_total`, `researching_total` | FBA Inventory v1 `InventorySummary` → `sellerSku`, `asin`, `fnSku`, `condition`, `lastUpdatedTime`, `totalQuantity`, and under `inventoryDetails`: `fulfillableQuantity`, `inboundWorkingQuantity`, `inboundShippedQuantity`, `inboundReceivingQuantity`, `reservedQuantity.totalReservedQuantity`, `unfulfillableQuantity.totalUnfulfillableQuantity`, `researchingQuantity.totalResearchingQuantity` |

Quantities are `int | None`. `None` means Amazon omitted the field — which it
does for the whole `inventoryDetails` block unless `details=true` was
requested — and is never silently turned into `0`. A boolean in a quantity
field is treated as absent, not as `1`. `seller_sku` and the report ids are
required; a payload without them raises `AmazonError` naming the missing key
and the keys that were present.

---

## 5. Error taxonomy

All in `app/integrations/amazon/errors.py`, all subclasses of `AmazonError`,
each with a `guidance` string for whoever reads the log or CLI output.

| Exception | Raised when | Retried? |
|---|---|---|
| `AmazonConfigurationError` | Credentials missing, unknown marketplace id, marketplace not in `AMAZON_REGION`, `SP_API_DEFAULT_MARKETPLACE` set, or the library reports missing credentials | No |
| `AmazonAuthError` | Login with Amazon rejected the refresh token or client credentials (`sp_api.auth.exceptions.AuthorizationError`) | **Never** — the same credentials give the same answer |
| `AmazonRateLimited` | 429 on every attempt. Carries `retry_after_seconds` if Amazon sent one | Was retried; this is the exhausted result |
| `AmazonTransientError` | 500 / 503 / 504 on every attempt. Carries `status_code` | Was retried; this is the exhausted result |
| `AmazonReportFailed` | `fetch_report` saw `CANCELLED` or `FATAL`, `DONE` without a document id, or ran out of time. Carries `report_id`, `processing_status`, `timed_out` | No |
| `AmazonError` (base) | Any other definite answer — a 400 for a bad report type, a 404, a payload without a required field | No |

The library's exception for each status is caught inside the client; none of
them, and none of the library's response types, cross the boundary.

---

## 6. Retry policy

Applied to every library call by `AmazonClient._call_response`:

- **Retried:** the library's `SellingApiRequestThrottledException` (429),
  `SellingApiServerException` (500), `SellingApiTemporarilyUnavailableException`
  (503) and `SellingApiGatewayTimeoutException` (504) — the four
  `RETRYABLE_EXCEPTIONS`.
- **Not retried:** everything else. An LWA failure, a 400, a 403, a 404, a 409
  are definite answers; repeating them only repeats the mistake more slowly.
- **Attempts:** `AMAZON_MAX_ATTEMPTS` (default 5) in total, so at most four
  retries. No sleep after the final failure.
- **Delay:** Amazon's `Retry-After` header if present, otherwise
  `2^(attempt-1)` seconds multiplied by jitter in `[0.5, 1.0)`. Either way
  capped at `MAX_BACKOFF_SECONDS` (60). Jitter matters even for one client:
  without it, retries after a throttling burst synchronise onto the same
  instants.
- **Pagination and retries compose:** a throttled page of inventory summaries
  is re-requested with the same `nextToken`, so a retry never skips or repeats
  a page.
- **Polling is not retrying:** `fetch_report` waits `poll_interval_s` between
  status checks regardless of outcome; the retry policy applies to each
  individual status call inside that loop.

`sleep` and the clock are injectable, so the tests cover backoff growth, the
cap, `Retry-After`, exhaustion, and the polling timeout without waiting.

---

## 7. Orders ingestion

`app/services/amazon_orders.py` is the first consumer of the client. One
call, `run_orders_sync(session, organization_id, window_start, window_end,
trigger_type, triggered_by_user_id=None, client=None)`, performs one run and
returns its closed `AmazonSyncRun`.

### The run, step by step

1. **Validate the window.** Timezone-aware UTC, end after start, end not in
   the future, and at most `MAX_WINDOW_DAYS` (30) long — Amazon's limit for
   this report, refused here with a message that says so.
   `trailing_window(days=30)` gives the scheduler `[now - 30d, now]`.
2. **Claim the slot.** A `RUNNING` row is inserted and committed in its own
   transaction before anything else happens. The partial unique index
   `uq_amazon_sync_runs_running_job` is the lock: a second attempt raises
   `OrdersSyncAlreadyRunning` and fetches nothing.
3. **Fetch.** `client.fetch_report("GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE_GENERAL", …)`
   — request, poll, download, through the read-only client.
4. **Parse** (below).
5. **Upsert and close, in one transaction.** Lines are upserted, the run is
   set to `COMPLETED` (or `COMPLETED_WITH_ERRORS` when any row was
   rejected) with its five counts, and an audit event
   `amazon.orders_sync.completed` is recorded with actor type `SYSTEM` — all
   in the same transaction (ADR 0006).
6. **On any failure**, the run is closed as `FAILED` in a fresh transaction
   with the exception class and message in `error_details`, audited as
   `amazon.orders_sync.failed`, and the exception is re-raised. This is a
   `try/except/finally`: a run row can end `RUNNING` only if the process
   dies between the claim and the `finally`.

### Parsing the report

The flat file is read with the `csv` module (tab delimiter), decoded as
UTF-8 (BOM tolerated) with a fallback to Latin-1. Twelve columns are
required — `amazon-order-id`, `purchase-date`, `last-updated-date`,
`order-status`, `fulfillment-channel`, `sales-channel`, `sku`, `asin`,
`item-status`, `quantity`, `currency`, `item-price` — and a report missing
any of them fails the run with the missing names in the message.

**The `ship-*` columns are never read.** The retained `raw` dict is built
from the required-column list, not from the row, so `ship-city`,
`ship-state`, `ship-postal-code` and `ship-country` (and `product-name`)
cannot reach the database by accident. A unit test asserts `raw` holds
exactly the twelve columns; a schema test asserts the table has no
PII-shaped column.

Rows are **aggregated per `(amazon-order-id, sku)`** — the report has no
order-item id, and one order can list the same SKU twice. Quantities are
summed; statuses, price and timestamps come from the line with the latest
`last-updated-date`. Timestamps are parsed as ISO 8601 and normalised to
UTC. A row that cannot be interpreted (a non-integer quantity, a blank SKU,
an unparseable date) is counted in `rows_failed` and described in
`error_details.rows` with its row number; the rest of the report still
loads. A price without a currency is dropped rather than stored, because
the table's check forbids the pair.

### The upsert

`INSERT … ON CONFLICT (organization_id, amazon_order_id, seller_sku) DO
UPDATE`, in batches of 500, with two rules enforced in SQL *and* counted in
Python:

- data columns change only when the incoming `last_updated_at` is **newer**
  than the stored one (`CASE WHEN excluded.last_updated_at >
  amazon_order_lines.last_updated_at …`) — re-running an old window cannot
  regress a line;
- `last_seen_sync_run_id` is set on every line the report contained,
  changed or not; `first_seen_sync_run_id` is never touched after insert.

Counts (`rows_created` / `rows_updated` / `rows_unchanged`) come from a
read of the existing keys in the same transaction; the one-`RUNNING`-run
index is what makes that read safe.

### A defect this work found in the foundation

`app/db/transaction.py` had `session.commit()` in an `else` branch. A
constraint violation raised *by the commit itself* — an object added in the
body and first flushed at commit time — was therefore never rolled back,
and the session was left in a pending-rollback state that failed every
later statement. The orders sync hit it on its second call. `commit()` now
sits inside the `try` in both `transaction()` and `savepoint()`, and a
regression test in `test_transactions.py` covers the commit-time path.
Phase 2's vendor CRUD would have found the same defect on its first
duplicate code.

---

## 8. Inventory ingestion

`app/services/amazon_inventory.py` — `run_inventory_sync(session,
organization_id, trigger_type, triggered_by_user_id=None, client=None,
listings_sink=None)` — has the same run/transaction/audit shape as the
orders sync (the shared pieces now live in `app/services/amazon_runs.py`:
`open_run`, `close_run`, `fail_run`). Job type `FBA_INVENTORY`; audit
actions `amazon.inventory_sync.completed` / `.failed`.

### Two reads, one snapshot per SKU

1. **FBA Inventory** — `iter_inventory_summaries(details=True,
   page_delay_s=AMAZON_INVENTORY_PAGE_DELAY_S)`. The default delay of 0.6 s
   between pages keeps a 450-SKU account (≈ 9 pages of 50) under the
   endpoint's ~2 requests/second without waiting for a 429 to say so.
2. **The merchant listings report** — `GET_MERCHANT_LISTINGS_ALL_DATA` via
   `fetch_report`. FBA Inventory knows nothing about merchant-fulfilled
   stock; this report's `fulfillment-channel` column does. Eight columns are
   read: `seller-sku`, `quantity`, `fulfillment-channel`, `asin1`,
   `product-id`, `product-id-type`, `item-name`, `status`. Rows whose
   channel is `DEFAULT` are FBM and their `quantity` is the FBM quantity; a
   blank quantity stays `None`; an unknown channel value is kept verbatim
   and **not** treated as FBM. `product-id-type` is mapped 1 → ASIN,
   2 → ISBN, 3 → UPC, 4 → EAN for the listings mapping that follows.

The two are merged per seller SKU into one `AmazonInventorySnapshot` with
`captured_at` = the run's start time:

- every FBA summary produces a row; an omitted quantity becomes `0`
  explicitly, and `raw` keeps the API's own values (`None` preserved) so a
  coerced zero is traceable;
- an FBM listing for a SKU FBA returned sets `fbm_quantity` on that row;
- an FBM listing for a SKU FBA did **not** return produces an FBM-only row
  — zero FBA quantities, the FBM quantity, `raw.source = "listings_report"`;
- an FBM-only listing with no `asin1` cannot satisfy the table's `NOT NULL`
  ASIN and is counted as a failed row with a reason rather than invented.

**Snapshots are append-only.** Every run inserts its own rows and never
touches an earlier run's; `uq_amazon_inventory_snapshots_run_sku` makes a
duplicate within a run impossible, and a duplicate FBA summary is counted as
failed rather than allowed to trip it. Counts: `rows_seen` = summaries +
listings rows, `rows_created` = snapshots written, `rows_failed` = listings
rows rejected + merge failures, `error_details.fbm_only` = how many SKUs
came only from the report.

The parsed listings rows are handed, in memory, to `listings_sink` when one
is given — that is the hook for the listings→product mapping, so it needs
no second report fetch. A named `TODO(prompt-11)` in the service marks
where the direct call replaces the hook.

---

## 9. What is still unproven

The client has run only against fakes. Until B8 is answered and the probe
step runs it against the real account, these remain assumptions:

- that the seller's SP-API application has the **Inventory and Order
  Tracking** and **Product Listing** roles, without which the inventory and
  listings calls return 403;
- the actual latency of report generation for this seller, which sets a
  realistic `timeout_s`;
- the real throttling behaviour under a first 30-day backfill of order
  lines, and whether `Retry-After` is sent;
- the charset Amazon declares for this seller's flat-file reports (the
  library decodes with a fallback of ISO-8859-1 if none is declared);
- the exact column set and timestamp format of the live orders report — the
  parser's fixture follows Amazon's documentation, and the required twelve
  columns are checked on every run, but the report has not been pulled;
- the same for the merchant listings report, and whether its
  `fulfillment-channel` values on this account are exactly `DEFAULT` and
  `AMAZON_NA`;
- the real page count and latency of FBA Inventory for this account, which
  is what `AMAZON_INVENTORY_PAGE_DELAY_S` should be tuned against.

Each is recorded when observed, in the same way
[nineyard-field-mapping.md](nineyard-field-mapping.md) records Nineyard
findings.
