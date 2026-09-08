# Nineyard Field Mapping

Status: **Entirely unverified.** No probe run has been executed yet.
Last updated: 2026-09-08

---

## How to read this document

Every Nineyard field name below is `UNVERIFIED`. That is not a placeholder to be
filled in from a guess — it means **no response has been observed**, and nobody
should write mapping code against any row still marked that way.

| Marker | Meaning |
|---|---|
| `UNVERIFIED` | No observation. Do not build against it. |
| `CONFIRMED` | Seen in a probe run; record the run and the date. |
| `ABSENT` | Probed for and demonstrably not present. |
| `N/A` | Confirmed not applicable to this endpoint. |

Fill it in from a probe run:

```bash
cd backend
.venv/Scripts/python -m app.cli.nineyard_probe --save-samples
```

The domain columns on the right are real — they exist in the migrated schema
([database-schema.md](database-schema.md)). It is only the Nineyard side that is
unknown.

---

## 1. The question that matters most

CLAUDE.md §5 makes the **Nineyard Catalog Item Number** the primary business
reference for a product, and `products.catalog_item_number` is uniquely
constrained per organization on that basis.

**Which Nineyard field is it?** `UNVERIFIED`.

Candidates to look for in the `/api/Items` response — *guesses about what to
look for, not claims about what exists*: `itemNumber`, `catalogItemNumber`,
`itemId`, `sku`, `partNumber`, `number`, `code`.

Until this is answered, nothing downstream can be built. Two properties must
hold and both need checking, not assuming:

1. It is **stable** — the same product carries the same value across syncs.
2. It is **unique** within a company.

A probe run shows the field exists. Only a second run days apart, or a
conversation with Nineyard, shows it is stable.

---

## 2. `GET /api/Items` → `products`

| Nineyard field | Type | Domain column | Notes |
|---|---|---|---|
| `UNVERIFIED` | `UNVERIFIED` | `products.catalog_item_number` | **Blocking.** See §1. Unique per organization. |
| `UNVERIFIED` | `UNVERIFIED` | `products.name` | Indexed btree + trigram for search. |
| `UNVERIFIED` | `UNVERIFIED` | `products.brand` | Nullable. |
| `UNVERIFIED` | `UNVERIFIED` | `products.manufacturer` | Nullable. |
| `UNVERIFIED` | `UNVERIFIED` | `products.description` | Nullable. Never a match key (CLAUDE.md §5.2). |
| `UNVERIFIED` | `UNVERIFIED` | `products.pack_size` | Integer, must be > 0. Relates to blocking question B3. |
| `UNVERIFIED` | `UNVERIFIED` | `products.unit_of_measure` | Nullable. |
| `UNVERIFIED` | `UNVERIFIED` | `products.status` | Must map onto `ACTIVE / INACTIVE / DISCONTINUED / ARCHIVED`. The source vocabulary is unknown. |
| `UNVERIFIED` | `UNVERIFIED` | `products.is_active` | May be derivable from status rather than a separate field. |
| — | — | `products.nineyard_last_seen_at` | Set by the sync, not mapped from a response field. |
| `UNVERIFIED` | `UNVERIFIED` | `products.attributes` (JSONB) | Destination for observed fields with no dedicated column. |

**Open:** does an Item carry identifiers (UPC/GTIN) directly, or only through
Skus? That determines whether §3 or §4 populates `product_identifiers`.

---

## 3. `GET /api/Items` → `product_identifiers`

One row per identifier. The unique index makes a UPC resolve to exactly one
product per tenant, which is what makes match priority 1 unambiguous.

| Nineyard field | `identifier_type` | Notes |
|---|---|---|
| `UNVERIFIED` | `CATALOG_ITEM_NUMBER` | Same source field as §1; mirrored here for uniform lookup. |
| `UNVERIFIED` | `UPC` | Normalisation is ours: strip non-digits, expand UPC-E, validate the check digit, compare as GTIN-14. |
| `UNVERIFIED` | `EAN` | May not exist. |
| `UNVERIFIED` | `GTIN` | May not exist. |
| `UNVERIFIED` | `MPN` | May not exist. |
| `UNVERIFIED` | `ASIN` | May come from Nineyard, or only from a marketplace source (blocking question B7). |

`raw_value` always stores exactly what Nineyard sent; `normalized_value` is our
canonical form. Both are kept — normalising in place destroys the evidence
needed to debug a bad match.

**Open:** are identifiers a flat field, a nested object, or an array of typed
identifiers? The probe's sanitised sample answers this by shape.

---

## 4. `GET /api/Skus` → `vendor_products` and/or `marketplace_listings`

**The relationship between Items and Skus is unknown, and it is the second most
important open question.** "Sku" could mean:

- a vendor's SKU for an item → `vendor_products.vendor_sku`
- a marketplace listing SKU → `marketplace_listings.seller_sku`
- an internal variant of an item → likely a `products` row of its own
- something else entirely

Which of these it is decides how three tables get populated. Do not guess.

| Nineyard field | Type | Candidate destination | Notes |
|---|---|---|---|
| `UNVERIFIED` | `UNVERIFIED` | *(depends on the above)* | The SKU value. |
| `UNVERIFIED` | `UNVERIFIED` | link to the parent Item | Foreign key back to Items — field name and shape unknown. |
| `UNVERIFIED` | `UNVERIFIED` | `marketplace_listings.marketplace_id` | Only if Skus are marketplace listings. |
| `UNVERIFIED` | `UNVERIFIED` | `marketplace_listings.asin` | Only if Skus carry Amazon data. |
| `UNVERIFIED` | `UNVERIFIED` | `vendor_products.pack_size` | Blocking question B3. |
| `UNVERIFIED` | `UNVERIFIED` | `vendor_products.unit_of_measure` | |

**Note on mapping status.** Whatever this becomes, an imported row must **not**
arrive as `mapping_status = APPROVED`. Approval is a human act
([ADR 0010](decisions/0010-identifier-model-and-mapping-placement.md)), and a
check constraint requires an approver and a timestamp on any approved row.

---

## 5. `GET /api/Vendors` → `vendors`

| Nineyard field | Type | Domain column | Notes |
|---|---|---|---|
| `UNVERIFIED` | `UNVERIFIED` | `vendors.code` | Unique per organization. Stored uppercase (check constraint). |
| `UNVERIFIED` | `UNVERIFIED` | `vendors.name` | Indexed btree + trigram. |
| `UNVERIFIED` | `UNVERIFIED` | `vendors.status` | Must map onto `ACTIVE / INACTIVE / ON_HOLD`. Source vocabulary unknown. |
| `UNVERIFIED` | `UNVERIFIED` | `vendors.currency` | ISO 4217, three characters, uppercase. |
| `UNVERIFIED` | `UNVERIFIED` | `vendors.default_lead_time_days` | Nullable, non-negative. |
| `UNVERIFIED` | `UNVERIFIED` | `vendors.contact_email` | Nullable. |
| `UNVERIFIED` | `UNVERIFIED` | `vendors.contact_phone` | Nullable. |
| — | — | `vendors.timezone` | Governs interpretation of vendor-supplied dates. Probably not in Nineyard; likely configured locally. |

**Open:** is the Nineyard vendor identifier suitable as `vendors.code`, or is
`code` a local convention with the Nineyard id belonging in `source_records`?
The latter is more likely and would be cleaner.

---

## 6. `GET /api/PurchaseOrders` → *no Milestone 1 destination*

**This endpoint has no mapping target, deliberately.** Purchase-order generation
is explicitly out of scope for Milestone 1 (CLAUDE.md §3), and there is no
purchase-order table in the schema.

It is probed anyway for three reasons, none of which involve storing the data:

1. To learn whether the integration account can read it at all — a 403 here is a
   finding worth having before a later milestone depends on it.
2. To observe how Nineyard represents vendor and item references in a second
   context, which is corroborating evidence for §2 and §5.
3. To see the paging mechanism on what is likely a larger collection.

**Do not build a purchase-order table, model, or sync from this.** Record the
observations here and stop.

| Observation | Value |
|---|---|
| Readable by the integration account | `UNVERIFIED` |
| Response envelope shape | `UNVERIFIED` |
| How a vendor is referenced | `UNVERIFIED` |
| How an item is referenced | `UNVERIFIED` |

---

## 7. Cross-cutting unknowns

### Paging — `UNVERIFIED`

| Question | Answer |
|---|---|
| Does paging exist? | `UNVERIFIED` |
| Request parameter names | `UNVERIFIED` |
| Response metadata field names | `UNVERIFIED` |
| Default page size | `UNVERIFIED` |
| Maximum page size | `UNVERIFIED` |
| Is a total count returned? | `UNVERIFIED` |

The probe reports paging-looking keys as **candidates**; confirming what they
mean needs a second run with a deliberately small page.

### Incremental sync — `UNVERIFIED`

`nineyard_sync_runs.cursor` exists on the assumption that incremental sync
*might* be possible. If there is no `updatedSince` filter, full catalog pulls are
the only option and that column stays unused — harmless, but it should be a known
fact rather than a hope.

### Rate limits — `UNVERIFIED`

Not documented. The client honours a numeric `Retry-After`. Whether Nineyard
sends one is unknown.

### Envelope shape — `UNVERIFIED`

Bare array, or an object with a records key? Consistent across all four groups,
or different per endpoint? The probe answers both.

### Timestamps — `UNVERIFIED`

Format, and whether they carry a timezone. Everything is stored as UTC
`TIMESTAMPTZ`, so a naive local timestamp from Nineyard would need a documented
assumption about which zone it is in.

### Deletions — `UNVERIFIED`

Does an item disappear from the collection, or carry a deleted flag? This
determines how the sync detects removals. Products are soft-deactivated, never
hard-deleted, so a wrong answer here silently deactivates live products.

---

## 8. Before writing any mapping code

- [ ] Probe run completed and a sanitised sample saved
- [ ] §1 answered — the Catalog Item Number field is identified
- [ ] Its stability confirmed across two runs, not assumed
- [ ] §4 answered — the Items ↔ Skus relationship is understood
- [ ] Paging confirmed, or confirmed absent
- [ ] Every group's readability by the integration account recorded
- [ ] Status vocabularies observed and mapped onto our enums
- [ ] Deletion semantics established
- [ ] This document has no `UNVERIFIED` left in the fields the sync depends on

Only then: the anti-corruption layer, then the sync service. Writing the mapper
first and adjusting it against reality is the failure mode ADR 0007 exists to
prevent — the code compiles, its tests pass against invented fixtures, and it is
wrong in a way that surfaces only once real data flows through it.
