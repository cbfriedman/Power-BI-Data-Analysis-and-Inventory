# Amazon SP-API Integration

Status: **Read-only client built; nothing calls it yet.** No ingestion,
tables, scheduler, endpoint or CLI exist. The client has been exercised only
against fakes — it has not been run against the real seller account
(blocking question **B8**).
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
| `iter_inventory_summaries(*, details=True)` | `Iterator[InventorySummary]` | Every FBA inventory summary for the marketplace, following `nextToken` until exhausted. `details=True` requests the `inventoryDetails` block, which is where the inbound quantities live. |

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

## 7. What is still unproven

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
  library decodes with a fallback of ISO-8859-1 if none is declared).

Each is recorded when observed, in the same way
[nineyard-field-mapping.md](nineyard-field-mapping.md) records Nineyard
findings.
