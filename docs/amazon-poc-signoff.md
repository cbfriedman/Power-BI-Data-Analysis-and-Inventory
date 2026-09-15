# Amazon SP-API Proof of Concept — Validation and Sign-off

Status: **PENDING — not validated.** No live call has been made. As of
2026-09-15 the Login with Amazon credentials are not present on the
development machine (`.env` last modified 2026-09-08; no `AMAZON_*` variable
in `.env`, `backend/.env` or the environment). Every evidence section below
is empty on purpose; nothing here is filled in until the command that
produces it has actually run. Blocking question **B8** in
[phase1-status.md](phase1-status.md).

This document lists the client's seven requirements verbatim and, under each,
the exact procedure that produces the evidence. When the credentials arrive,
run the procedure top to bottom and paste the output — and nothing else —
into the evidence blocks.

---

## Before running anything

```powershell
# 1. Credentials present? Names and lengths only; values are never printed.
Select-String -Path .env -Pattern '^AMAZON_' | ForEach-Object {
    $name, $value = $_.Line -split '=', 2; "$name len=$($value.Length)"
}

# 2. An organization exists for the account to write into (AMAZON_ORGANIZATION_SLUG
#    if more than one). The application never creates one implicitly.
psql "$env:DATABASE_URL" -c "select slug, is_active from organizations"

# 3. Schema at head.
cd backend; .\.venv\Scripts\alembic current
```

---

## 1. "SP-API/LWA authentication"

**Procedure**

```powershell
cd backend
.\.venv\Scripts\python -m app.cli.amazon_poc auth 2>&1 | Tee-Object -FilePath ..\storage\diagnostics\amazon\auth.log
# Expected: exit 0 and one line: "token obtained; expires in 3600s at <iso>".
# Then prove nothing leaked. Every count must be 0:
$secret = (Select-String -Path ..\.env -Pattern '^AMAZON_LWA_CLIENT_SECRET=').Line -split '=',2 | Select-Object -Last 1
$refresh = (Select-String -Path ..\.env -Pattern '^AMAZON_LWA_REFRESH_TOKEN=').Line -split '=',2 | Select-Object -Last 1
(Select-String -Path ..\storage\diagnostics\amazon\auth.log -SimpleMatch $secret).Count
(Select-String -Path ..\storage\diagnostics\amazon\auth.log -SimpleMatch $refresh).Count
(Select-String -Path ..\storage\diagnostics\amazon\auth.log -Pattern 'Atza\|').Count
```

**Evidence** — *(pending)*

Dry run without credentials, 2026-09-15 — the configuration path and the
no-leak property, which is all that can be shown today:

```
$ python -m app.cli.amazon_poc auth
configuration error: Missing required settings: AMAZON_LWA_CLIENT_ID, AMAZON_LWA_CLIENT_SECRET, AMAZON_LWA_REFRESH_TOKEN, AMAZON_SELLER_ID
exit code: 2
secret-shaped strings (Atza|, Atzr|, amzn1.oa2-cs) in stdout+stderr: 0
```

---

## 2. "Retrieval of the sales data required for 7/14/30-day velocity"

**Procedure**

```powershell
.\.venv\Scripts\python -m app.cli.amazon_poc run 2>&1 | Tee-Object -FilePath ..\storage\diagnostics\amazon\run.log
# Expected: one line per run (orders ×2 windows, inventory, listings), all COMPLETED, exit 0.
```

```sql
select job_type, status, trigger_type,
       window_start, window_end,
       rows_seen, rows_created, rows_updated, rows_unchanged, rows_failed,
       completed_at - started_at as duration,
       error_message
from amazon_sync_runs
order by started_at;
```

**Evidence** — *(pending)*

---

## 3. "Retrieval of relevant inventory and inbound inventory"

**Procedure** — the inventory run is in step 2. Then:

```sql
select count(*) as skus,
       sum(fulfillable) as fulfillable,
       sum(inbound_working + inbound_shipped + inbound_receiving) as inbound,
       count(fbm_quantity) as skus_with_fbm,
       max(captured_at) as captured_at
from amazon_inventory_snapshots s
where sync_run_id = (select id from amazon_sync_runs
                     where job_type = 'FBA_INVENTORY' and status = 'COMPLETED'
                     order by started_at desc limit 1);
```

**Evidence** — *(pending)*

---

## 4. "Mapping Amazon SKUs to our Nineyard Catalog Item #/UPC structure"

**Procedure**

```sql
-- How many seller SKUs are in each state. This is the measure of how much
-- Nineyard SKU data is still needed: APPROVED came from the catalog source,
-- PENDING is a UPC suggestion awaiting a person, UNMAPPED has nothing to go on.
select mapping_status, mapping_method, count(*)
from marketplace_listings
group by 1, 2 order by 1, 2;

-- What the exception queue holds, by reason.
select reason, status, count(*)
from product_mapping_exceptions
where marketplace_listing_id is not null
group by 1, 2 order by 1, 2;
```

**Evidence** — *(pending)*

Expected on first run: with no Nineyard sync yet, `product_identifiers` holds
no `AMAZON_SKU` rows, so **no listing can reach `APPROVED`**; UPC-bearing
listings whose UPC exists on a product become `PENDING`, the rest
`UNMAPPED` with `NO_MATCH`. That count is the honest size of the gap.

---

## 5. "Storage of the data in PostgreSQL"

**Procedure**

```sql
select 'amazon_sync_runs' t, count(*) from amazon_sync_runs
union all select 'amazon_order_lines', count(*) from amazon_order_lines
union all select 'amazon_inventory_snapshots', count(*) from amazon_inventory_snapshots
union all select 'marketplace_listings', count(*) from marketplace_listings
union all select 'product_mapping_exceptions', count(*) from product_mapping_exceptions
union all select 'audit_events (amazon.%)', count(*) from audit_events where action like 'amazon.%';

-- No buyer data, checked against the live table, not the model:
select column_name from information_schema.columns
where table_name = 'amazon_order_lines'
  and (column_name like 'ship%' or column_name like 'buyer%');   -- must be empty
```

**Velocity table** (the client-facing view of the stored data):

```powershell
.\.venv\Scripts\python -m app.cli.amazon_poc velocity --level product --top 25
```

**Cross-check against Seller Central** — Business Reports › By ASIN › Detail
Page Sales and Traffic, same 30-day window, three SKUs, side by side:

| Seller SKU | Window (UTC) | Units, this system (30 d) | Units, Seller Central | Difference | Explanation |
|---|---|---|---|---|---|
| *(pending)* | | | | | |
| *(pending)* | | | | | |
| *(pending)* | | | | | |

Differences to expect and account for: Seller Central's day boundaries are
in the marketplace's local time (PST/PDT for amazon.com) while this window
is UTC; Seller Central counts *ordered* units while this system stores the
latest `quantity_ordered` per (order, SKU) and excludes `Cancelled`; orders
still `Pending` may or may not be in either figure depending on when each
was read.

**Evidence** — *(pending)*

---

## 6. "Scheduled data ingestion"

**Procedure** — set `AMAZON_ENABLED=true`, start the API
(`uvicorn app.main:app`), leave it for 48 hours, then:

```sql
select job_type, status, trigger_type, started_at, completed_at - started_at as duration,
       rows_seen, rows_created, rows_updated, rows_failed
from amazon_sync_runs
where trigger_type = 'SCHEDULED'
order by started_at;
-- Expected over 48 h: 2 × orders (each as two windows), ~48 × inventory, 2 × listings; no RUNNING rows.
```

**Evidence** — *(pending)*

---

## 7. "Basic error handling and logging"

**Procedure — failure drill**

```powershell
# Terminal 1
.\.venv\Scripts\python -m app.cli.amazon_poc sync-orders --days 30
# While the report is being polled (log line amazon.report.status), disconnect the network.
# Expected: exit 1; one line "orders ...: FAILED — <AmazonTransientError or AmazonRateLimited message>".
# Reconnect, then:
.\.venv\Scripts\python -m app.cli.amazon_poc sync-orders --days 30
# Expected: exit 0, COMPLETED; the FAILED row remains as history.
```

```sql
select job_type, status, started_at, completed_at, error_message, error_details
from amazon_sync_runs
where job_type = 'ORDERS_REPORT'
order by started_at desc limit 3;
```

The log line to paste is the JSON `amazon.run.failed` event, which carries
`run_id`, `error_type` and `error_message` and — by construction — no
credential.

**Evidence** — *(pending)*

---

## Sign-off

| | |
|---|---|
| Validated by | *(pending)* |
| Date | *(pending)* |
| Account | *(seller id is not recorded here; it is configuration)* |
| Outcome | *(pending)* |
