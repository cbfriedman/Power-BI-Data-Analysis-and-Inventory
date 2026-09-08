# Nineyard Integration

Status: **Read-only diagnostic only.** No synchronisation service exists yet,
and none should be written until this document's open questions are answered
from observation rather than assumption (ADR 0007).
Last updated: 2026-09-08

---

## 1. Why a probe before a client

Blocking question **B1** asked for the Nineyard API specification. What arrived
is the authentication endpoint and four read-only endpoint groups — enough to
*ask* the API what it returns, not enough to *assume* it.

Everything else a synchronisation service needs is still unknown: the response
envelope, the field names, whether paging exists and what it is called, whether
the integration account can read all four groups. Guessing at those and writing
a sync service would produce code that compiles, passes its own tests, and is
wrong in a way nobody discovers until real data flows through it.

So the order is: probe, record, then build. The probe's findings go into
[nineyard-field-mapping.md](nineyard-field-mapping.md), and the anti-corruption
layer is written only once that document has no `UNVERIFIED` placeholders left
in the fields the sync depends on.

---

## 2. What is actually known

Only this. Everything else in this repository treats Nineyard as unknown.

### Authentication

```
POST https://backyard.nineyard.com/api/OAuth/UsernameToken
Content-Type: application/json

{
  "email": "<email>",
  "password": "<password>",
  "companyId": <integer>
}
```

Response fields expected: `accessToken`, `expiresIn`, `expires`.

Even these are treated as *expected rather than confirmed*: the client accepts a
response missing `expiresIn` or `expires` and reports them as absent, because
"documented" and "observed" are different things and only the probe can close
that gap.

Protected requests use `Authorization: Bearer <accessToken>`.

### Read-only endpoint groups under investigation

| Group | Path |
|---|---|
| Items | `GET /api/Items` |
| Skus | `GET /api/Skus` |
| Vendors | `GET /api/Vendors` |
| PurchaseOrders | `GET /api/PurchaseOrders` |

### What is not known

Response envelope shape · field names and types · nullability · paging mechanism
and parameter names · total-count semantics · rate limits · whether the
integration account can read every group · the relationship between Items and
Skus · which field is the **Catalog Item Number** that CLAUDE.md §5 makes the
primary business reference.

That last one is the single most important unknown. The entire product-identity
model depends on it.

---

## 3. Safety design

This tool reads. It cannot write, and that is a structural property rather than
a policy.

### Mutation is impossible, not merely discouraged

`NineyardClient` exposes exactly three public methods: `authenticate`, `get`,
and `close`. There is no `post`, `put`, `patch` or `delete`, and no method that
takes an HTTP verb as an argument. The one POST the client makes is
authentication, and its path is a module constant that cannot be redirected.

A test asserts the public method set, so adding a mutating verb breaks the build
rather than passing review unnoticed.

```python
def test_get_is_the_only_public_request_method() -> None:
    assert public_methods(NineyardClient) == {"authenticate", "close", "get"}
```

The CLI reinforces this: `--endpoints` accepts only names from the read-only
allowlist, so `--endpoints UpdateInventory` is refused as an unknown endpoint.

### Credentials

Read from environment variables only, via the single typed settings object.
`NINEYARD_PASSWORD` is a `SecretStr`, so it cannot be printed by an f-string, a
repr, or a stack trace.

The email, the password and the token are **never** logged. The only
token-derived value that reaches a log is a 12-character SHA-256 prefix — enough
to tell two runs apart, useless as a credential. It is explicitly allowlisted in
the redaction filter for that reason.

A test runs authentication through the real logging pipeline and asserts that
none of the three appear in the output.

### Diagnostic output carries no data

Sample values are replaced by *descriptions of themselves*:

| Real value | Recorded as |
|---|---|
| `"012345678905"` | `"<str len=12 digits>"` |
| `"Blue Widget 12-pack"` | `"<str len=19 text>"` |
| `"Acme Distribution"` | `"<str len=17 text>"` |
| `998877` | `"<int>"` |
| `true` | `true` |

The descriptor keeps the diagnostic signal — a 12-digit numeric string is
recognisably a UPC — and carries none of the data. Booleans and nulls are kept
literal because they identify nobody, and knowing whether a flag is a real
boolean or a `"Y"`/`"N"` string is exactly what the probe is for.

Field *names* are always preserved verbatim. They are the point of the exercise.

Samples are written under `storage/diagnostics/nineyard/`, which `.gitignore`
excludes wholesale — a second line of defence behind sanitisation.

### Retries are for transient failures only

| Condition | Retried |
|---|---|
| Connection error, timeout | Yes |
| 429, 500, 502, 503, 504 | Yes |
| 401, 403, 404, and every other 4xx | **No** |

Retrying a 401 repeats the same mistake more slowly. Backoff is exponential with
jitter, honours `Retry-After` when the server sends a numeric one, and is capped
at 30 seconds per wait so a diagnostic run cannot hang.

### Status handling

Each status gets its own exception carrying actionable guidance:

| Status | Meaning for the probe |
|---|---|
| 401 | Credentials rejected, or the token expired mid-run. `companyId` being wrong is a plausible cause. |
| 403 | Authenticated but not permitted. **A useful finding** — record which groups the account can read. |
| 404 | The path is wrong. On a collection endpoint this means the path, not empty data. |
| 429 | Rate limited. `Retry-After` is honoured and reported. |
| 5xx | Nineyard's side. Retried, then reported. |
| non-JSON body | Usually a login redirect or a proxy. Reported with the content type. |

A failing endpoint is recorded and the run continues — discovering that the
account reads Items but not PurchaseOrders is precisely the kind of finding this
exists to produce. Only an authentication failure aborts, because four identical
401s are noise rather than data.

---

## 4. Running it

### First, without credentials

`--dry-run` prints the exact request plan and opens no socket. A test asserts
that constructing an HTTP client during a dry run fails, so this is a guarantee
rather than an intention.

```bash
cd backend
.venv/Scripts/python -m app.cli.nineyard_probe --dry-run     # Windows
.venv/bin/python -m app.cli.nineyard_probe --dry-run         # macOS / Linux
```

### Then, after adding credentials

Add to `.env` in the repository root — never to any tracked file:

```dotenv
NINEYARD_BASE_URL=https://backyard.nineyard.com
NINEYARD_EMAIL=you@example.com
NINEYARD_PASSWORD=your-nineyard-password
NINEYARD_COMPANY_ID=1234
```

**The exact safe command:**

```bash
cd backend
.venv/Scripts/python -m app.cli.nineyard_probe --save-samples
```

That authenticates once, issues four GETs, prints a report, and writes a
sanitised JSON file to `storage/diagnostics/nineyard/`.

### Narrowing the run

```bash
# One group at a time, which is the gentler way to start
.venv/Scripts/python -m app.cli.nineyard_probe --endpoints Items

# Ask for a small page once a paging parameter name is known
.venv/Scripts/python -m app.cli.nineyard_probe --endpoints Items --page-param pageSize=5

# Machine-readable output
.venv/Scripts/python -m app.cli.nineyard_probe --json
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Every requested endpoint returned a readable response |
| 1 | Configuration problem — credentials missing |
| 2 | Authentication failed |
| 3 | One or more endpoints failed |

---

## 5. What the probe reports

Per run: token fingerprint, `expiresIn`, `expires`, and every top-level key the
token response actually contained.

Per endpoint: HTTP status · content type · elapsed time · top-level type and
keys · which key held the record array · record count · field names with
per-field presence counts · paging-metadata candidates · a sanitised sample.

Two conventions keep it honest:

- **Candidates are labelled as candidates.** The probe does not decide that
  `totalCount` is the record total. It reports that a key by that name exists
  and holds an integer.
- **Presence counts, not nullability.** A field in 2 of 3 records is reported as
  `(in 2/3 records)`. That is an observation. Concluding the column is nullable
  needs more than one page.

---

## 6. After the probe runs

1. Fill in [nineyard-field-mapping.md](nineyard-field-mapping.md), replacing
   `UNVERIFIED` with observed field names.
2. Answer the open questions in §7 of that document — several need more than one
   probe run, and one needs a person at Nineyard.
3. Only then write the anti-corruption layer (ADR 0007): Nineyard DTOs and a
   mapper into domain models, with no Nineyard field name reaching `app/models/`.
4. Then the sync service, `nineyard_sync_runs`, and `source_records` payload
   retention.

The probe is not a prototype of the client. It is throwaway instrumentation, and
the real client should be written against evidence rather than by promoting this
code.

---

## 7. Files

| Path | Purpose |
|---|---|
| [`app/integrations/nineyard/client.py`](../backend/app/integrations/nineyard/client.py) | Read-only HTTP client, auth, retries, status mapping |
| [`app/integrations/nineyard/probe.py`](../backend/app/integrations/nineyard/probe.py) | Response description; invents nothing |
| [`app/integrations/nineyard/sanitize.py`](../backend/app/integrations/nineyard/sanitize.py) | Structure-preserving value redaction |
| [`app/integrations/nineyard/errors.py`](../backend/app/integrations/nineyard/errors.py) | Error taxonomy with guidance |
| [`app/cli/nineyard_probe.py`](../backend/app/cli/nineyard_probe.py) | CLI entry point |
| `tests/unit/test_nineyard_*.py` | 85 tests, all against mocked transports |

No test in the suite makes a network request.
