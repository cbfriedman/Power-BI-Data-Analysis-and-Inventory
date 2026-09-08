"""Outbound integrations with external systems.

Each external system gets its own subpackage and an anti-corruption layer: its
payload shapes are parsed into local DTOs and translated into domain models, so
no external field name reaches ``app.models`` (ADR 0007).

Empty at scaffold stage. The Nineyard client is phase 3 and is currently blocked
on blocking question B1.
"""
