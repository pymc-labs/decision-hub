"""FastAPI dependency-injection functions.

Provides reusable dependencies for settings, database connections,
S3 client access, and current-user extraction from JWT tokens.
"""

from collections.abc import Generator
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from jose import JWTError
from loguru import logger
from sqlalchemy.engine import Connection, Engine

from decision_hub.domain.auth import decode_jwt
from decision_hub.infra.cache import TTLCache
from decision_hub.models import User
from decision_hub.settings import Settings


def get_settings(request: Request) -> Settings:
    """Retrieve application settings from app state."""
    return request.app.state.settings


def get_engine(request: Request) -> Engine:
    """Retrieve the SQLAlchemy engine from app state."""
    return request.app.state.engine


def get_s3_client(request: Request):
    """Retrieve the boto3 S3 client from app state."""
    return request.app.state.s3_client


def get_cache(request: Request) -> TTLCache:
    """Retrieve the shared in-memory TTL cache from app state."""
    return request.app.state.cache


def get_connection(
    engine: Engine = Depends(get_engine),
) -> Generator[Connection, None, None]:
    """Yield a database connection inside a transaction.

    Commits automatically on successful request completion.
    Rolls back automatically if the request handler raises an exception.
    """
    with engine.begin() as conn:
        yield conn


def _user_from_payload(payload: dict) -> User:
    """Reconstruct a minimal ``User`` from a trusted JWT payload.

    We rely on JWT integrity instead of a DB lookup on every request — the
    payload is signed by us, so the orgs claim is as trustworthy as the
    JWT secret itself.
    """
    return User(
        id=UUID(payload["sub"]),
        github_id="",
        username=payload["username"],
        github_orgs=tuple(payload["github_orgs"]),
    )


def _decode_request_token(request: Request, settings: Settings) -> dict | None:
    """Decode the ``Authorization`` bearer token from *request*.

    Returns the decoded payload, or ``None`` if the header is missing, the
    token doesn't validate, or it predates the ``github_orgs`` refactor.
    Centralised so ``get_current_user`` and ``get_current_user_optional``
    can't drift apart on what counts as "valid".
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.removeprefix("Bearer ")
    try:
        payload = decode_jwt(token, settings.jwt_secret, settings.jwt_algorithm)
    except JWTError:
        return None

    # Tokens issued before the org refactor lack the github_orgs claim.
    if "github_orgs" not in payload:
        return None

    return payload


def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> User:
    """Extract and validate a JWT bearer token from the Authorization header.

    Raises:
        HTTPException 401: When the header is missing, malformed, or the
            token is invalid / expired / outdated.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid authorization header",
        )

    payload = _decode_request_token(request, settings)
    if payload is None:
        # Distinguish "we couldn't decode" from "we could decode but the
        # token is the old shape" so the CLI can tell the user to re-login.
        try:
            decode_jwt(
                auth_header.removeprefix("Bearer "),
                settings.jwt_secret,
                settings.jwt_algorithm,
            )
        except JWTError:
            logger.warning("Invalid JWT from {}", request.client.host if request.client else "unknown")
            raise HTTPException(status_code=401, detail="Invalid token") from None
        # Decoded fine — must be the missing-claim path.
        raise HTTPException(
            status_code=401,
            detail="Your session is outdated. Run 'dhub login' to refresh.",
        )

    return _user_from_payload(payload)


def get_current_user_optional(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> User | None:
    """Extract a JWT bearer token, returning ``None`` if missing or invalid.

    Use this for endpoints that support both authenticated and anonymous
    access (e.g. listing public skills). Never raises on bad tokens — the
    caller treats anything that fails to decode as "anonymous".
    """
    payload = _decode_request_token(request, settings)
    if payload is None:
        # Only log a warning if a header was actually present but invalid;
        # missing header is the normal anonymous case.
        if request.headers.get("Authorization"):
            logger.debug("Invalid JWT in optional auth context")
        return None
    return _user_from_payload(payload)
