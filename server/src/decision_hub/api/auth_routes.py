"""Authentication routes – GitHub Device Flow login."""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.engine import Connection

from decision_hub.api.deps import get_connection, get_settings
from decision_hub.domain.auth import create_jwt
from decision_hub.infra.database import upsert_user
from decision_hub.domain.orgs import sync_user_orgs
from decision_hub.infra.github import (
    AuthorizationPending,
    check_org_membership,
    get_github_user,
    list_user_orgs as github_list_user_orgs,
    poll_for_access_token,
    request_device_code,
)
from decision_hub.settings import Settings

logger = logging.getLogger(__name__)

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
    orgs: list[str] = []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/github/code", response_model=DeviceCodeResponseSchema)
async def start_device_flow(
    settings: Settings = Depends(get_settings),
) -> DeviceCodeResponseSchema:
    """Start GitHub Device Flow.

    Returns a user_code for the user to enter at verification_uri, plus the
    device_code the client uses to poll for completion.
    """
    result = await request_device_code(settings.github_client_id)
    return DeviceCodeResponseSchema(
        user_code=result.user_code,
        verification_uri=result.verification_uri,
        device_code=result.device_code,
        interval=result.interval,
    )


@router.post("/github/token", response_model=TokenResponse)
async def exchange_token(
    body: TokenRequest,
    conn: Connection = Depends(get_connection),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Exchange a device_code for a JWT access token.

    Polls GitHub until the user completes authorisation, upserts the user
    in the local database, and returns a signed JWT.
    """
    try:
        gh_token = await poll_for_access_token(settings.github_client_id, body.device_code)
        gh_user = await get_github_user(gh_token)
    except AuthorizationPending:
        raise HTTPException(status_code=428, detail="authorization_pending")
    except httpx.HTTPStatusError as exc:
        logger.warning("GitHub API returned %s: %s", exc.response.status_code, exc)
        raise HTTPException(
            status_code=502,
            detail=f"GitHub API error: {exc.response.status_code}",
        )
    except RuntimeError as exc:
        logger.warning("GitHub device flow error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    if settings.require_github_org:
        username = gh_user["login"]
        if not await check_org_membership(gh_token, settings.require_github_org, username):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Access restricted to members of the "
                    f"'{settings.require_github_org}' GitHub organization"
                ),
            )

    username = gh_user["login"]
    user = upsert_user(conn, str(gh_user["id"]), username)

    # Fetch the user's GitHub orgs and sync to DB
    github_org_logins: list[str] = []
    try:
        gh_orgs = await github_list_user_orgs(gh_token)
        github_org_logins = [o["login"] for o in gh_orgs]
    except Exception:
        logger.warning(
            "Failed to fetch GitHub orgs for %s; falling back to personal namespace only",
            username,
            exc_info=True,
        )

    org_slugs = sync_user_orgs(conn, user.id, github_org_logins, username)

    jwt_token = create_jwt(
        str(user.id),
        user.username,
        settings.jwt_secret,
        settings.jwt_algorithm,
        settings.jwt_expiry_hours,
        github_orgs=org_slugs,
    )
    return TokenResponse(access_token=jwt_token, username=user.username, orgs=org_slugs)
