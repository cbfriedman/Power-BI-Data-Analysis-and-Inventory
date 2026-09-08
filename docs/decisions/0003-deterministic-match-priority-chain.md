# 0003. Deterministic match priority chain with a mandatory exception queue

- **Status:** Accepted
- **Date:** 2026-09-07

## Context

Vendor files identify products inconsistently: sometimes a UPC, sometimes only a
vendor SKU, often a free-text description, occasionally nothing reliable at all.
A wrong match here is not a cosmetic bug — it propagates into inventory,
replenishment, and eventually purchase orders in later milestones, where it
becomes money spent on the wrong product. Fuzzy matching that is right 95% of the
time produces a 5% error rate that nobody can see and nobody can audit.

## Decision

Matching evaluates rules in a strict priority order and stops at the first rule
returning **exactly one** product:

1. Exact normalized UPC
2. Exact Nineyard Catalog Item Number
3. Previously approved vendor SKU mapping
4. Previously approved Amazon SKU mapping
5. Controlled match suggestion — **requires human approval**

Binding constraints:

- **A product description is never sufficient on its own for an automatic
  match.** Description similarity may only contribute to a priority-5 suggestion
  that a human approves.
- **Any uncertainty enters the exception queue.** "Uncertain" means: no rule
  fired, a rule matched more than one product, or only a suggestion exists. A
  rule returning multiple products yields `ambiguous` — it never falls through to
  a lower-priority rule and never picks a candidate.
- **Approved mappings are permanent.** They feed priorities 3 and 4 on every
  later import and are never recomputed, expired, or overwritten by an automated
  run — only by an explicit, audited human action that records supersession.
- **Matching is deterministic.** Identical input against identical mapping state
  always yields the identical outcome and the identical rule attribution.
- Every row records which rule fired and the full evaluation trail, so any match
  can be explained after the fact.

## Alternatives considered

| Option | Why not |
|---|---|
| Fuzzy or ML matching with a confidence threshold | Non-deterministic, unexplainable, and silently wrong at the margin — unacceptable when the output drives purchasing |
| Auto-accept high-scoring description matches | Directly violates the product identity rules; description collisions between pack sizes and variants are common |
| Fall through to the next rule on ambiguity | Turns "we found two candidates" into a silent arbitrary choice — the exact failure mode this design exists to prevent |

## Consequences

**Positive** — every match is explainable and reproducible. Human judgment is
captured once and reused permanently. Wrong matches become visible work items
rather than invisible data corruption.

**Negative** — the exception queue is real, ongoing human work, and its volume is
the main adoption risk (see risk R4). Onboarding a new vendor is slower at first,
until its mappings accumulate. We accept this: the cost of review is bounded and
visible, while the cost of a silent mismatch is neither.

**Follow-ups** — measure the exception rate on the first real vendor file, and
build bulk-approval tooling for repeated identical cases before the queue is
judged unusable. Do not respond to queue volume by loosening these rules.
