"""Outbound integrations with external systems.

Each external system gets its own subpackage and an anti-corruption layer: its
payload shapes are parsed into local DTOs and translated into domain models, so
no external field name reaches ``app.models`` (ADR 0007).

The Nineyard subpackage currently holds a **read-only diagnostic only** — see
docs/nineyard-integration.md. The synchronisation client is written once the
probe has established the response shapes, not before.
"""
