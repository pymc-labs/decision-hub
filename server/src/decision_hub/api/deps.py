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


# Sentinel result returned by ``_decode_bearer_payload`` when the incoming
# request has no bearer header, or the token is malformed, expired, or
# missing the mandatory ``github_orgs`` claim. The caller (required- vs
# optional-auth dependency) decides whether that is a 401 or a ``None``.
class _AuthReject:
    __slots__ = ("detail", "log", "status_code")

    def __init__(self, status_code: int, detail: str, log: str) -> None:
        self.status_code = status_code
        self.detail = detail
        self.log = log


def _decode_bearer_payload(request: Request, settings: Settings) -> User | _AuthReject:
    """Decode the bearer JWT into a :class:`User`, or return a rejection.

    Extracted from ``get_current_user`` / ``get_current_user_optional`` so
    both dependencies share exactly one implementation of header parsing,
    token decoding, and the "outdated claim" check.  The optional variant
    swallows rejections; the required variant raises HTTP 401.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return _AuthReject(401, "Missing or invalid authorization header", "")

    token = auth_header.removeprefix("Bearer ")

    try:
        payload = decode_jwt(token, settings.jwt_secret, settings.jwt_algorithm)
    except JWTError:
        client_host = request.client.host if request.client else "unknown"
        return _AuthReject(401, "Invalid token", f"Invalid JWT from {client_host}")

    # Tokens issued before the org refactor lack the github_orgs claim.
    # Prompt the user to re-authenticate so they get a fresh token.
    if "github_orgs" not in payload:
        return _AuthReject(
            401,
            "Your session is outdated. Run 'dhub login' to refresh.",
            f"Outdated token for user={payload.get('username')} (missing github_orgs claim)",
        )

    # The JWT 'sub' claim holds the user id and 'username' holds the login.
    # We trust the signed token and avoid a DB lookup on every request.
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
    result = _decode_bearer_payload(request, settings)
    if isinstance(result, _AuthReject):
        if result.log:
            logger.warning(result.log)
        raise HTTPException(status_code=result.status_code, detail=result.detail)
    return result


def get_current_user_optional(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> User | None:
    """Extract and validate a JWT bearer token, returning None if missing or invalid.

    Unlike :func:`get_current_user`, this does not raise HTTP 401 for
    unauthenticated requests. Use it for endpoints that support both
    authenticated and anonymous access.
    """
    result = _decode_bearer_payload(request, settings)
    if isinstance(result, _AuthReject):
        # DEBUG so a valid-JWT-with-outdated-claim case isn't lost, but not
        # WARNING (it would spam logs for every anon browse).
        if result.log:
            logger.debug("Optional-auth rejected: {}", result.log)
        return None
    return result
