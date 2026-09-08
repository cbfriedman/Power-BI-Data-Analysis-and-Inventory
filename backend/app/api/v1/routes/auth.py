"""Authentication routes.

Two endpoints: one to obtain a development token, one to inspect the resulting
identity. Both disappear or change shape when Microsoft Entra ID is introduced —
token issuance moves to Entra, and ``/me`` keeps working unchanged because it
only depends on :class:`~app.core.security.Principal`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_client_ip, get_current_principal
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.security import DevJwtAuthenticationBackend, Principal, load_principal
from app.db.session import get_db
from app.db.transaction import transaction
from app.models.identity import User
from app.schemas.auth import DevTokenRequest, PrincipalResponse, TokenResponse
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])

_logger = get_logger(__name__)


@router.post(
    "/dev-token",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a development access token",
    responses={404: {"description": "The endpoint is disabled, or no such active user exists."}},
)
def issue_dev_token(
    payload: DevTokenRequest,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> TokenResponse:
    """Mint a token for an existing user, for local development and tests.

    Two independent locks: ``DEV_AUTH_ENABLED`` must be set, and the environment
    must not be production. The settings validator already refuses to start a
    production process with the flag on, so this is defence in depth rather than
    the only guard.

    Disabled, it answers 404 rather than 403 — an endpoint that should not exist
    here should not advertise that it exists elsewhere.
    """
    if not settings.dev_auth_enabled or settings.is_production:
        raise NotFoundError("The requested resource does not exist.")

    user = session.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()

    if user is None or not user.is_active:
        # Same answer either way: whether an address is registered is not
        # something an unauthenticated caller gets to learn.
        _logger.warning("auth.dev_token_denied", email=payload.email)
        raise NotFoundError("The requested resource does not exist.")

    principal = load_principal(session, user.id)
    backend = DevJwtAuthenticationBackend(settings)
    token, expires_in = backend.issue_token(principal)

    # Token issuance is an authentication event and belongs in the trail. The
    # token itself is never recorded.
    with transaction(session):
        audit.record(
            session,
            organization_id=principal.organization_id,
            action="auth.dev_token_issued",
            entity_type="users",
            entity_id=principal.user_id,
            actor=principal,
            summary=f"Development token issued, valid {expires_in}s.",
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
        )

    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get(
    "/me",
    response_model=PrincipalResponse,
    summary="The authenticated actor",
    responses={401: {"description": "Missing or invalid credentials."}},
)
def read_current_principal(
    principal: Principal = Depends(get_current_principal),
) -> PrincipalResponse:
    """Return the caller's identity and effective roles.

    Roles come from the database on every call, not from the token, so a
    revocation is visible here immediately.
    """
    return PrincipalResponse(
        user_id=principal.user_id,
        organization_id=principal.organization_id,
        email=principal.email,
        display_name=principal.display_name,
        roles=sorted(role.value for role in principal.roles),
    )
