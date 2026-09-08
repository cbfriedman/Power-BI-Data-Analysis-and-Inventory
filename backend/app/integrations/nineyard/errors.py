"""Nineyard error taxonomy.

Each class answers a different question for whoever is reading the diagnostic
output: is this a credential problem, a permission problem, a wrong-path
problem, or the server having a bad day? Collapsing them into one exception
would make the probe's report useless, since "it failed" is exactly what the
probe exists to refine.
"""

from __future__ import annotations


class NineyardError(Exception):
    """Base for every Nineyard integration failure."""

    #: Short, actionable guidance shown in the probe report.
    guidance: str = "Inspect the response and retry."

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class NineyardConfigurationError(NineyardError):
    """Credentials or base URL are missing or unusable."""

    guidance = (
        "Set NINEYARD_EMAIL, NINEYARD_PASSWORD and NINEYARD_COMPANY_ID in .env. "
        "They are never read from anywhere else."
    )


class NineyardTransportError(NineyardError):
    """The request never produced an HTTP response.

    A DNS failure, a refused connection, or a timeout — raised only after the
    retry budget is exhausted, since these are the transient cases worth
    retrying.
    """

    guidance = (
        "Check network reachability and the base URL. This was retried and still "
        "failed to get any response."
    )


class NineyardAuthenticationError(NineyardError):
    """401 — the credentials or the token were rejected."""

    guidance = (
        "The credentials were rejected, or the token expired mid-run. Verify "
        "NINEYARD_EMAIL / NINEYARD_PASSWORD / NINEYARD_COMPANY_ID. Note that "
        "companyId is an integer and the wrong company is a plausible cause."
    )


class NineyardPermissionError(NineyardError):
    """403 — authenticated, but this account may not read this resource."""

    guidance = (
        "Authentication succeeded but the account lacks access to this endpoint. "
        "This is a useful finding: record which endpoints the integration account "
        "can actually read."
    )


class NineyardNotFoundError(NineyardError):
    """404 — the path does not exist, or the resource does not."""

    guidance = (
        "The endpoint path may differ from the one assumed here. A 404 on a "
        "collection endpoint means the path is wrong, not that the data is empty."
    )


class NineyardRateLimitError(NineyardError):
    """429 — too many requests."""

    guidance = (
        "Rate limited. The probe honours Retry-After; if this persists, the "
        "account's quota is lower than the probe's pacing assumes."
    )

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.retry_after_seconds = retry_after_seconds


class NineyardServerError(NineyardError):
    """5xx — the fault is on Nineyard's side."""

    guidance = (
        "Nineyard returned a server error. Retried and still failing; this is not "
        "something the client can fix."
    )


class NineyardUnexpectedStatusError(NineyardError):
    """Any other status the client was not told how to interpret."""

    guidance = "An unhandled status. Record it — it is a genuine finding about the API."


class NineyardProtocolError(NineyardError):
    """A response arrived but could not be understood.

    Most often HTML — a login page or an error page — where JSON was expected,
    which usually means the request never reached the API at all.
    """

    guidance = (
        "The response was not the JSON this endpoint was expected to return. "
        "An HTML body usually means a proxy, a login redirect, or a wrong path."
    )
