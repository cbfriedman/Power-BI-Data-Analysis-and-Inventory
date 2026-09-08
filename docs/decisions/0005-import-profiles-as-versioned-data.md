# 0005. Vendor import profiles are versioned data, not code

- **Status:** Accepted
- **Date:** 2026-09-07

## Context

Every vendor sends a differently shaped file: different column names and order,
different encodings and delimiters, different sheet layouts, different ways of
saying "out of stock", different pack-size conventions. Vendors are added
continuously, and they change their formats without notice.

If each vendor's quirks live in Python, onboarding a vendor means a code change,
a review, and a deploy — and the operations team cannot do it. Worse, when a
vendor changes their file, historical imports become uninterpretable because the
parsing logic has moved on.

## Decision

- A `vendor_import_profile` row fully describes how to read a vendor's file:
  format, encoding, delimiter, quote character, header row index, sheet
  selection, rows to skip, column-to-field mapping, normalization rules,
  quantity and price semantics, pack-size handling, and the availability-value
  mapping. Structured parts are JSONB.
- Profiles are **versioned**. Editing a profile creates a new version rather than
  mutating the existing one, and every `import_batch` records the exact profile
  version it ran under, so any historical import remains interpretable.
- Onboarding a vendor requires **no code change and no deployment** (AC-6.1).
- Each profile stores a `header_signature`. A file whose header does not match
  fails the batch immediately with a diff of expected vs. observed columns —
  columns are never mapped positionally as a fallback.
- Profile creation and edits are audited.

## Alternatives considered

| Option | Why not |
|---|---|
| A parser class per vendor | Every new vendor is a deploy; operations cannot onboard; historical parses are lost on refactor |
| Auto-detect columns by header text | Silently maps the wrong column when a vendor renames or reorders one — this is exactly risk R3 |
| Mutate profiles in place | Old batches become uninterpretable, and the report from last month can no longer be explained |

## Consequences

**Positive** — operations can onboard vendors and respond to format changes
without engineering. Historical imports stay explainable. Format drift fails
loudly and early rather than corrupting data quietly.

**Negative** — the profile schema becomes a de facto configuration language and
needs its own validation, its own tests, and a usable editing UI. A profile that
is expressive enough for every vendor risks becoming complex; genuinely
exceptional formats may still need code, and that should be a deliberate,
recorded exception rather than the default.

**Follow-ups** — blocking question B4 (real vendor files) drives the final
profile schema; B3 (pack-size policy) determines the `pack_size_handling` field.
Settle both before phase 4 to avoid a migration.
