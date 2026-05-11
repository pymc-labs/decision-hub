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


def _decode_bearer_user(request: Request, settings: Settings) -> User | None:
    """Decode the bearer token on a request into a User.

    Returns ``None`` for any of: missing header, malformed header,
    invalid/expired signature, missing ``github_orgs`` claim
    (tokens issued before the org refactor). Callers decide whether
    to translate ``None`` into HTTP 401 (required auth) or pass it
    through (optional auth).
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.removeprefix("Bearer ")

    try:
        payload = decode_jwt(token, settings.jwt_secret, settings.jwt_algorithm)
    except JWTError:
        return None

    if "github_orgs" not in payload:
        return None

    return User(
        id=UUID(payload["sub"]),
        github_id="",
        username=payload["username"],
        github_orgs=tuple(payload["github_orgs"]),
    )


def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> User:
    """Extract and validate a JWT bearer token from the Authorization header.

    Reconstructs a minimal User from the trusted JWT payload so that
    every authenticated request does not require a database round-trip.

    Raises:
        HTTPException 401: When the header is missing, malformed, or the
            token is invalid / expired / pre-orgs-refactor.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid authorization header",
        )

    user = _decode_bearer_user(request, settings)
    if user is None:
        # Distinguish "invalid signature/expired" from "missing
        # github_orgs claim" by re-running the decode once. The fast
        # path above already returned for malformed headers.
        token = auth_header.removeprefix("Bearer ")
        try:
            payload = decode_jwt(token, settings.jwt_secret, settings.jwt_algorithm)
        except JWTError:
            logger.warning("Invalid JWT from {}", request.client.host if request.client else "unknown")
            raise HTTPException(status_code=401, detail="Invalid token") from None

        # Tokens issued before the org refactor lack the github_orgs claim.
        # Prompt the user to re-authenticate so they get a fresh token.
        if "github_orgs" not in payload:
            logger.warning("Outdated token for user={} (missing github_orgs claim)", payload.get("username"))
            raise HTTPException(
                status_code=401,
                detail="Your session is outdated. Run 'dhub login' to refresh.",
            )

        # Should not reach here, but defensively raise.
        raise HTTPException(status_code=401, detail="Invalid token")
    return user


def get_current_user_optional(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> User | None:
    """Extract and validate a JWT bearer token, returning None if missing or invalid.

    Unlike get_current_user(), this does not raise HTTP 401 for unauthenticated
    requests. Use this for endpoints that support both authenticated and
    anonymous access.

    Returns:
        User object if valid token present, None otherwise.
    """
    user = _decode_bearer_user(request, settings)
    if user is None and request.headers.get("Authorization", "").startswith("Bearer "):
        # Log only when an invalid token was actually sent — silence
        # the much more common "no header" case.
        logger.debug("Invalid JWT in optional auth context")
    return user
