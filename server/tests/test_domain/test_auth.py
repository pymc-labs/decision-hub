"""Tests for decision_hub.domain.auth -- JWT creation and decoding."""

from datetime import UTC, datetime, timedelta

import pytest
from jose import JWTError
from jose import jwt as jose_jwt

from decision_hub.domain.auth import create_jwt, decode_jwt


def test_create_and_decode_jwt(jwt_secret: str) -> None:
    """Round-trip: create a token, decode it, and verify payload claims."""
    token = create_jwt(
        user_id="user-123",
        username="alice",
        secret=jwt_secret,
    )

    payload = decode_jwt(token, jwt_secret)

    assert payload["sub"] == "user-123"
    assert payload["username"] == "alice"
    assert "exp" in payload
    assert "iat" in payload


def test_decode_jwt_invalid_token(jwt_secret: str) -> None:
    """Decoding garbage should raise JWTError."""
    with pytest.raises(JWTError):
        decode_jwt("not-a-real-token", jwt_secret)


def test_decode_jwt_expired_token(jwt_secret: str) -> None:
    """A token with exp in the past should fail to decode."""
    past = datetime.now(UTC) - timedelta(hours=1)
    payload = {
        "sub": "user-456",
        "username": "bob",
        "github_orgs": [],
        "exp": past,
        "iat": past - timedelta(hours=1),
    }
    token = jose_jwt.encode(payload, jwt_secret, algorithm="HS256")

    with pytest.raises(JWTError):
        decode_jwt(token, jwt_secret)


def test_decode_jwt_wrong_secret() -> None:
    """A token signed with one secret cannot be verified with another."""
    token = create_jwt(
        user_id="user-789",
        username="carol",
        secret="secret-one",
    )

    with pytest.raises(JWTError):
        decode_jwt(token, "secret-two")


def test_decode_jwt_stale_org_membership(jwt_secret: str) -> None:
    """A token with stale org membership should still decode successfully.

    JWT tokens carry a snapshot of the user's github_orgs at token creation
    time. The token itself is still valid even if the org list is stale --
    downstream authorization checks must verify current membership against
    the database, not rely solely on the token claims.
    """
    token = create_jwt(
        user_id="user-999",
        username="dave",
        secret=jwt_secret,
        github_orgs=["old-org-that-no-longer-exists"],
    )

    payload = decode_jwt(token, jwt_secret)

    # Token decodes fine -- stale orgs are in the payload
    assert payload["sub"] == "user-999"
    assert payload["github_orgs"] == ["old-org-that-no-longer-exists"]
    # Downstream code should NOT trust this list without a DB check
