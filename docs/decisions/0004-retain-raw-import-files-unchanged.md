# 0004. Retain raw import files unchanged

- **Status:** Accepted
- **Date:** 2026-09-07

## Context

Import bugs are discovered late, usually when a downstream number looks wrong.
Diagnosing them requires knowing exactly what the vendor sent — not a normalized,
re-encoded, or partially parsed derivative of it. Vendors also dispute what they
sent. Without the original bytes, neither question can be settled, and a parser
fix cannot be validated by replaying history.

## Decision

- The uploaded file is written to storage **before any parsing begins**, exactly
  as received, byte for byte.
- A SHA-256 checksum is computed at upload and stored on `import_file`. Retrieval
  must reproduce the identical checksum.
- The stored object is never modified, re-encoded, normalized in place, lossily
  compressed, or deleted by normal processing.
- Metadata is recorded alongside it, never applied to it: original filename,
  size, declared MIME type, detected encoding, uploader, and UTC timestamp.
- The checksum is unique. Re-uploading an identical file is detected and requires
  explicit confirmation rather than silently creating a second batch.
- Storage sits behind a `StorageBackend` protocol (local filesystem for
  development, S3-compatible for deployment) so the destination is late-binding.

## Alternatives considered

| Option | Why not |
|---|---|
| Store only parsed rows | Cannot diagnose a parser bug, replay history against a fixed parser, or settle a dispute with a vendor |
| Normalize encoding on write | Destroys evidence of the encoding problem you will later need to debug |
| Delete files after a successful import | The problems that need the original are found long after the import "succeeded" |

## Consequences

**Positive** — every import is reproducible and auditable. Parser fixes can be
validated by replaying real historical files. Row-level errors trace to a real
line in a real retained file.

**Negative** — storage grows without bound under assumption A7 (no retention
policy in Milestone 1), and raw files may contain commercially sensitive pricing,
so access control and encryption at rest are required in deployment.

**Follow-ups** — blocking question B5 settles the storage destination and any
retention or compliance requirement.
