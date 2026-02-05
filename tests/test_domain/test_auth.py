"""Tests for decision_hub.domain.auth -- JWT creation and decoding."""

import time

import pytest
from jose import JWTError

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
    """A token with 0 expiry hours should be expired immediately."""
    token = create_jwt(
        user_id="user-456",
        username="bob",
        secret=jwt_secret,
        expiry_hours=0,
    )
    # The token has exp == iat (both set to "now"), so by the time we
    # decode it the clock has moved forward and it should be expired.
    time.sleep(1)

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
