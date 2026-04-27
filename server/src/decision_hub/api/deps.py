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


class _JWTReason:
    """Why a JWT failed to resolve to a user. Used by the shared parser."""

    MISSING = "missing"
    INVALID = "invalid"
    OUTDATED = "outdated"


def _user_from_jwt(request: Request, settings: Settings) -> tuple[User | None, str | None]:
    """Decode a Bearer JWT into a ``User``.

    Returns ``(user, None)`` on success, or ``(None, reason)`` for any of:
    missing/malformed Authorization header, invalid signature/expired token,
    or token predating the ``github_orgs`` claim. Callers decide whether
    to raise 401 (auth-required routes) or fall back to anonymous access.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None, _JWTReason.MISSING

    token = auth_header.removeprefix("Bearer ")
    try:
        payload = decode_jwt(token, settings.jwt_secret, settings.jwt_algorithm)
    except JWTError:
        return None, _JWTReason.INVALID

    if "github_orgs" not in payload:
        return None, _JWTReason.OUTDATED

    user = User(
        id=UUID(payload["sub"]),
        github_id="",
        username=payload["username"],
        github_orgs=tuple(payload["github_orgs"]),
    )
    return user, None


def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> User:
    """Extract and validate a JWT bearer token from the Authorization header.

    Reconstructs a minimal User from the trusted JWT payload so that
    every authenticated request does not require a database round-trip.

    Raises:
        HTTPException 401: When the header is missing, malformed, or the
            token is invalid / expired.
    """
    user, reason = _user_from_jwt(request, settings)
    if user is not None:
        return user

    if reason == _JWTReason.MISSING:
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    if reason == _JWTReason.INVALID:
        logger.warning("Invalid JWT from {}", request.client.host if request.client else "unknown")
        raise HTTPException(status_code=401, detail="Invalid token")
    # Outdated: pre-org-refactor token. Prompt re-auth so the client picks
    # up a token that includes the github_orgs claim.
    logger.warning("Outdated JWT — missing github_orgs claim")
    raise HTTPException(
        status_code=401,
        detail="Your session is outdated. Run 'dhub login' to refresh.",
    )


def get_current_user_optional(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> User | None:
    """Extract and validate a JWT bearer token, returning None if missing or invalid.

    Unlike get_current_user(), this does not raise HTTP 401 for unauthenticated
    requests. Use this for endpoints that support both authenticated and
    anonymous access.
    """
    user, reason = _user_from_jwt(request, settings)
    if reason == _JWTReason.INVALID:
        logger.debug("Invalid JWT in optional auth context")
    return user
