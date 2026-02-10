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


def get_connection(
    engine: Engine = Depends(get_engine),
) -> Generator[Connection, None, None]:
    """Yield a database connection inside a transaction.

    Commits automatically on successful request completion.
    Rolls back automatically if the request handler raises an exception.
    """
    with engine.begin() as conn:
        yield conn


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
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid authorization header",
        )

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

    # The JWT 'sub' claim holds the user id and 'username' holds the login.
    # We trust the signed token and avoid a DB lookup on every request.
    return User(
        id=UUID(payload["sub"]),
        github_id="",
        username=payload["username"],
        github_orgs=tuple(payload["github_orgs"]),
    )
