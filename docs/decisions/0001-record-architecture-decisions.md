# 0001. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-09-07

## Context

This system is delivered over multiple milestones, and Milestone 1 fixes several
constraints — UUID identity, a strict match priority chain, raw file retention —
that later contributors will encounter without the reasoning behind them. Rules
without recorded rationale get quietly "simplified" by whoever finds them
inconvenient, which in this system means silently wrong product matches.

## Decision

Record architecturally significant decisions as ADRs in `docs/decisions/`, using
the template in `0000-template.md` and the process in `README.md`. Accepted ADRs
are immutable: a change of direction is a new ADR that supersedes the old one.

An "architecturally significant" decision is one that is expensive to reverse,
constrains future work, or would otherwise look arbitrary to a newcomer.

## Alternatives considered

| Option | Why not |
|---|---|
| Rationale in code comments | Not discoverable, gets deleted with the code it explains |
| A wiki or external doc tool | Drifts from the code; not reviewable in the same pull request |
| No records | Rules get relaxed without anyone noticing the cost |

## Consequences

**Positive** — decisions are reviewable in pull requests alongside the code they
govern, and the reasoning survives contributor turnover.

**Negative** — a small ongoing writing cost, and discipline is required to keep
accepted records immutable rather than editing them.
