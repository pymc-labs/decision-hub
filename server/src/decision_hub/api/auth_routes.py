"""Authentication routes – GitHub Device Flow login."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.engine import Connection

from decision_hub.api.deps import get_connection, get_settings
from decision_hub.domain.auth import create_jwt
from decision_hub.infra.database import upsert_user
from decision_hub.infra.github import (
    AuthorizationPending,
    check_org_membership,
    get_github_user,
    poll_for_access_token,
    request_device_code,
)
from decision_hub.settings import Settings

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class DeviceCodeResponseSchema(BaseModel):
    """Values the client needs to display to the user for device-flow login."""
    user_code: str
    verification_uri: str
    device_code: str
    interval: int


class TokenRequest(BaseModel):
    """Client submits the device_code to poll for a completed GitHub login."""
    device_code: str


class TokenResponse(BaseModel):
    """JWT token returned after successful authentication."""
    access_token: str
    token_type: str = "bearer"
    username: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/github/code", response_model=DeviceCodeResponseSchema)
def start_device_flow(
    settings: Settings = Depends(get_settings),
) -> DeviceCodeResponseSchema:
    """Start GitHub Device Flow.

    Returns a user_code for the user to enter at verification_uri, plus the
    device_code the client uses to poll for completion.
    """
    result = request_device_code(settings.github_client_id)
    return DeviceCodeResponseSchema(
        user_code=result.user_code,
        verification_uri=result.verification_uri,
        device_code=result.device_code,
        interval=result.interval,
    )


@router.post("/github/token", response_model=TokenResponse)
def exchange_token(
    body: TokenRequest,
    conn: Connection = Depends(get_connection),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Exchange a device_code for a JWT access token.

    Polls GitHub until the user completes authorisation, upserts the user
    in the local database, and returns a signed JWT.
    """
    try:
        gh_token = poll_for_access_token(settings.github_client_id, body.device_code)
    except AuthorizationPending:
        raise HTTPException(status_code=428, detail="authorization_pending")

    gh_user = get_github_user(gh_token)

    if settings.require_github_org:
        username = gh_user["login"]
        if not check_org_membership(gh_token, settings.require_github_org, username):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Access restricted to members of the "
                    f"'{settings.require_github_org}' GitHub organization"
                ),
            )

    user = upsert_user(conn, str(gh_user["id"]), gh_user["login"])
    conn.commit()

    jwt_token = create_jwt(
        str(user.id),
        user.username,
        settings.jwt_secret,
        settings.jwt_algorithm,
        settings.jwt_expiry_hours,
    )
    return TokenResponse(access_token=jwt_token, username=user.username)
