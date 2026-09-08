# 0010. Identifier model, and where approved mappings live

- **Status:** Accepted
- **Date:** 2026-09-08
- **Relates to:** [ADR 0002](0002-product-identity-uuid-and-catalog-item-number.md),
  [ADR 0003](0003-deterministic-match-priority-chain.md)

## Context

The match priority chain reads four different kinds of identifier, each with a
different scope:

| Priority | Identifier | Scope |
|---|---|---|
| 1 | Normalized UPC | Global within the tenant |
| 2 | Catalog Item Number | Global within the tenant |
| 3 | Approved vendor SKU mapping | One vendor |
| 4 | Approved Amazon SKU mapping | One marketplace listing |

Two questions followed: where identifiers live, and where an *approved* mapping
is recorded. Planning had sketched a separate `vendor_product_mapping` table;
the Milestone 1 schema brief instead names `product_identifiers` and
`marketplace_listings` as required entities and asks that identifier records
carry source-system, vendor, and marketplace context.

A third constraint: "avoid placing multiple Amazon SKUs in one column." One
catalog item may have many Amazon SKUs (CLAUDE.md §5).

## Decision

**Identifiers.** `product_identifiers` is the single lookup surface the matching
engine reads. Each row carries `identifier_type`, `raw_value`,
`normalized_value`, `source_system`, and the optional context columns `vendor_id`
and `marketplace_listing_id`. A check constraint enforces that the context
matches the type — a `VENDOR_SKU` must have a vendor and no listing, an
`AMAZON_SKU` must have a listing and no vendor, everything else must have
neither — so an inconsistent identifier cannot be written.

Uniqueness is expressed as three partial indexes rather than one, because the
scopes genuinely differ: global values resolve to one product per tenant, vendor
SKUs are unique within their vendor, listing SKUs within their listing. All are
partial on `is_active`, so a retired identifier keeps its history without
blocking reuse.

**Marketplace listings.** `marketplace_listings` holds one row per marketplace
SKU, with `asin`, `marketplace_id`, and listing state. Never a delimited column.

**Approved mappings live on the row that owns the identifier**, not in a separate
mapping table:

- priority 3 reads `vendor_products.product_id` where `mapping_status = 'APPROVED'`
- priority 4 reads `marketplace_listings.product_id` where `mapping_status = 'APPROVED'`

Both carry `approved_by` and `approved_at`, and both have a check constraint
making an `APPROVED` row without a product and an approver impossible. The
decision that *created* the mapping is preserved separately and permanently in
`product_mapping_exceptions`, and every status change is recorded in
`audit_events`.

## Alternatives considered

| Option | Why not |
|---|---|
| A separate `vendor_product_mappings` table | The mapping is one-to-one with the vendor product; a second table adds a join to the hot matching path and a second place for the two to disagree. History is already preserved by the exception record and the audit trail. |
| Store Amazon SKUs as a delimited string or array on `products` | Unqueryable, unindexable, and makes priority 4 unimplementable. Explicitly ruled out by the brief. |
| One unique index over `(type, normalized_value)` for all identifiers | Wrong for vendor SKUs: two vendors using the same SKU string for different products is normal, and a global index would reject the second one. |
| Nullable context with no check constraint | Permits a `VENDOR_SKU` with no vendor — an identifier whose scope is unknown, which matching cannot use safely. |

## Consequences

**Positive** — one indexed lookup surface for the matching engine, correct
scoping per identifier kind, and mapping state that cannot be internally
inconsistent. Approved mappings sit exactly where a query for "what is this
vendor SKU?" already looks.

**Negative** — an `AMAZON_SKU` identifier row duplicates
`marketplace_listings.seller_sku`. That is deliberate: the listing is the
authoritative record, the identifier is the uniform index. Keeping them in step
is the writing code's responsibility, and is worth an integrity test once the
sync and import paths exist.

Superseding a mapping updates a status rather than inserting a new row, so the
full mapping *history* lives in `audit_events` rather than in the mapping table
itself. If reconstructing mapping history becomes a common query, a dedicated
history table is the natural follow-up.
