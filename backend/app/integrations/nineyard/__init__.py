"""Nineyard integration.

Currently a **read-only diagnostic** only. There is no synchronisation service
here yet, deliberately: the API's response shapes have not been observed, and
ADR 0007 says the client is developed against evidence rather than guesses.

The probe (:mod:`app.integrations.nineyard.probe`) exists to gather that
evidence. Its findings feed docs/nineyard-field-mapping.md, and only once that
document has no "unverified" placeholders left does the anti-corruption layer
and the sync service get built.

Nothing in this package can mutate anything in Nineyard: the client exposes one
read method and no HTTP verb parameter.
"""

from app.integrations.nineyard.client import (
    AUTH_PATH,
    NineyardClient,
    NineyardConfig,
    TokenInfo,
)
from app.integrations.nineyard.probe import (
    READ_ONLY_ENDPOINTS,
    EndpointReport,
    ProbeReport,
    probe_endpoint,
    run_probe,
)

__all__ = [
    "AUTH_PATH",
    "READ_ONLY_ENDPOINTS",
    "EndpointReport",
    "NineyardClient",
    "NineyardConfig",
    "ProbeReport",
    "TokenInfo",
    "probe_endpoint",
    "run_probe",
]
