"""Authentication routes – GitHub Device Flow login."""

import httpx
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.engine import Connection

from decision_hub.api.deps import get_connection, get_settings
from decision_hub.domain.auth import create_jwt
from decision_hub.domain.orgs import sync_org_github_metadata, sync_user_orgs
from decision_hub.infra.database import upsert_user
from decision_hub.infra.github import (
    AuthorizationPending,
    check_org_membership,
    get_github_user,
    list_user_orgs as github_list_user_orgs,
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
        logger.warning("GitHub API returned {}: {}", exc.response.status_code, exc)
        raise HTTPException(
            status_code=502,
            detail=f"GitHub API error: {exc.response.status_code}",
        )
    except RuntimeError as exc:
        logger.warning("GitHub device flow error: {}", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    allowed_orgs = settings.required_github_orgs
    if allowed_orgs:
        username = gh_user["login"]
        is_member = False
        for org in allowed_orgs:
            if await check_org_membership(gh_token, org, username):
                is_member = True
                break
        if not is_member:
            logger.warning("User {} denied access — not in required orgs {}", username, allowed_orgs)
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Access restricted to members of: "
                    f"{', '.join(allowed_orgs)}"
                ),
            )

    username = gh_user["login"]
    user = upsert_user(conn, str(gh_user["id"]), username)
    logger.info("User authenticated: {} (id={})", username, user.id)

    # Fetch the user's GitHub orgs and sync to DB
    github_org_logins: list[str] = []
    try:
        gh_orgs = await github_list_user_orgs(gh_token)
        github_org_logins = [o["login"] for o in gh_orgs]
    except Exception:
        logger.opt(exception=True).warning(
            "Failed to fetch GitHub orgs for {}; falling back to personal namespace only",
            username,
        )

    org_slugs = sync_user_orgs(conn, user.id, github_org_logins, username)
    logger.debug("Synced orgs for {}: {}", username, org_slugs)

    # Sync GitHub metadata (avatar, email, description) for each org.
    # Best-effort: failures are logged but don't block login.
    try:
        await sync_org_github_metadata(conn, gh_token, org_slugs, username)
    except Exception:
        logger.opt(exception=True).warning(
            "Failed to sync GitHub metadata for {}; continuing", username,
        )

    jwt_token = create_jwt(
        str(user.id),
        user.username,
        settings.jwt_secret,
        settings.jwt_algorithm,
        settings.jwt_expiry_hours,
        github_orgs=org_slugs,
    )
    return TokenResponse(access_token=jwt_token, username=user.username, orgs=org_slugs)
