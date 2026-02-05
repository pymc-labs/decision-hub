"""JWT token creation and decoding for authentication."""

from datetime import datetime, timedelta, timezone

from jose import jwt


def create_jwt(
    user_id: str,
    username: str,
    secret: str,
    algorithm: str = "HS256",
    expiry_hours: int = 8760,
) -> str:
    """Create a long-lived JWT token.

    Args:
        user_id: Unique identifier for the user (stored as 'sub' claim).
        username: Username included in the token payload.
        secret: Secret key used to sign the token.
        algorithm: JWT signing algorithm.
        expiry_hours: Token lifetime in hours (default: 1 year).

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "exp": now + timedelta(hours=expiry_hours),
        "iat": now,
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_jwt(
    token: str,
    secret: str,
    algorithm: str = "HS256",
) -> dict:
    """Decode and validate a JWT token.

    Args:
        token: Encoded JWT string.
        secret: Secret key used to verify the token signature.
        algorithm: JWT signing algorithm.

    Returns:
        Decoded token payload as a dictionary.

    Raises:
        jose.JWTError: If the token is invalid, expired, or tampered with.
    """
    return jwt.decode(token, secret, algorithms=[algorithm])
