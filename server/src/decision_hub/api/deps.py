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


class _AuthFailure(Exception):
    """Signal that the bearer token is absent, malformed, or expired."""

    def __init__(self, message: str, *, outdated: bool = False) -> None:
        self.message = message
        self.outdated = outdated


def _decode_bearer(request: Request, settings: Settings) -> User:
    """Extract and validate a bearer token; return the User it encodes.

    Raises :class:`_AuthFailure` with a human-friendly message when the
    header is missing, the token is invalid or expired, or the token
    predates the ``github_orgs`` claim.  Never performs a DB lookup —
    the signed JWT is treated as the authoritative source of identity
    for the duration of the request.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise _AuthFailure("Missing or invalid authorization header")

    token = auth_header.removeprefix("Bearer ")
    try:
        payload = decode_jwt(token, settings.jwt_secret, settings.jwt_algorithm)
    except JWTError as exc:
        raise _AuthFailure("Invalid token") from exc

    # Tokens issued before the org refactor lack the github_orgs claim.
    # Flag as outdated so the caller can prompt the user to re-auth.
    if "github_orgs" not in payload:
        raise _AuthFailure(
            "Your session is outdated. Run 'dhub login' to refresh.",
            outdated=True,
        )

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
            token is invalid / expired.
    """
    try:
        return _decode_bearer(request, settings)
    except _AuthFailure as err:
        # Log invalid JWTs at WARNING so operators can spot credential-
        # stuffing attempts.  Outdated tokens are normal rotation traffic
        # and not noteworthy.
        if not err.outdated:
            logger.warning("Invalid JWT from {}", request.client.host if request.client else "unknown")
        raise HTTPException(status_code=401, detail=err.message) from None


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
    try:
        return _decode_bearer(request, settings)
    except _AuthFailure:
        return None
