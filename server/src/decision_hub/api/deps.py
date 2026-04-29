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

from decision_hub.api.rate_limit import client_ip
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


def _decode_user_from_request(request: Request, settings: Settings) -> User | None:
    """Decode and validate the JWT bearer token, returning a User or None.

    Returns ``None`` when the Authorization header is missing or malformed.
    Raises :class:`jose.JWTError` for tokens that fail signature or expiry
    validation, so callers can choose between strict (401) and optional
    (return-None) handling.

    Tokens issued before the org refactor lack the ``github_orgs`` claim;
    we treat those as missing rather than valid so users get a clear
    "re-authenticate" path.

    Reconstructs a minimal :class:`User` from the trusted JWT payload so
    every authenticated request avoids a database round-trip.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.removeprefix("Bearer ")
    payload = decode_jwt(token, settings.jwt_secret, settings.jwt_algorithm)

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

    Raises:
        HTTPException 401: When the header is missing, malformed, or the
            token is invalid / expired / from a pre-org-refactor session.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid authorization header",
        )

    try:
        user = _decode_user_from_request(request, settings)
    except JWTError:
        logger.warning("Invalid JWT from {}", client_ip(request))
        raise HTTPException(status_code=401, detail="Invalid token") from None

    if user is None:
        # The header existed (we just checked) but the payload lacked
        # the github_orgs claim — i.e. an old token from before the
        # org refactor.  Prompt re-auth.
        logger.warning("Outdated token from {}", client_ip(request))
        raise HTTPException(
            status_code=401,
            detail="Your session is outdated. Run 'dhub login' to refresh.",
        )

    return user


def get_current_user_optional(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> User | None:
    """Extract and validate a JWT bearer token, returning ``None`` if missing or invalid.

    Unlike :func:`get_current_user`, this does not raise HTTP 401 for
    unauthenticated requests.  Use it for endpoints that support both
    authenticated and anonymous access.
    """
    try:
        return _decode_user_from_request(request, settings)
    except JWTError:
        logger.debug("Invalid JWT in optional auth context")
        return None
