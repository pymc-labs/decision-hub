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


def _user_from_token(
    auth_header: str | None,
    settings: Settings,
    *,
    request: Request,
) -> User | None:
    """Decode a Bearer token and reconstruct the User from JWT claims.

    Returns ``None`` for any reason the token is unusable (missing header,
    not a Bearer, invalid signature/expiry, missing ``github_orgs`` claim).
    Callers decide whether to treat ``None`` as 401 or as anonymous.

    The signed JWT is the source of truth — we avoid a per-request DB
    round-trip by trusting the ``sub``, ``username``, and ``github_orgs``
    claims that the auth flow puts there.
    """
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.removeprefix("Bearer ")
    try:
        payload = decode_jwt(token, settings.jwt_secret, settings.jwt_algorithm)
    except JWTError:
        logger.debug(
            "Invalid JWT from {}",
            request.client.host if request.client else "unknown",
        )
        return None

    # Tokens issued before the org refactor lack the github_orgs claim;
    # treat them as missing so the user is prompted to re-authenticate.
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
        HTTPException 401: When the header is missing, malformed, the
            token is invalid / expired, or the token predates the
            ``github_orgs`` claim.
    """
    user = _user_from_token(request.headers.get("Authorization"), settings, request=request)
    if user is not None:
        return user

    # Distinguish "no header" from "stale/invalid token" for a clearer
    # error message — clients in the wild need to know which one fired.
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    raise HTTPException(
        status_code=401,
        detail="Your session is outdated or invalid. Run 'dhub login' to refresh.",
    )


def get_current_user_optional(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> User | None:
    """Extract a JWT bearer token, returning ``None`` if missing or invalid.

    Unlike :func:`get_current_user`, this never raises. Use it for endpoints
    that support both authenticated and anonymous access.
    """
    return _user_from_token(request.headers.get("Authorization"), settings, request=request)
