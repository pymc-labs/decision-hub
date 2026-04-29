"""Tests for stale token detection in get_current_user."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from jose import JWTError, jwt

from decision_hub.api.deps import (
    _decode_user_from_request,
    get_current_user,
    get_current_user_optional,
)


def _build_settings(secret: str = "test-secret-1234567890") -> SimpleNamespace:
    return SimpleNamespace(jwt_secret=secret, jwt_algorithm="HS256")


def _build_request(authorization: str | None) -> MagicMock:
    request = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {} if authorization is None else {"Authorization": authorization}
    return request


def _mint(settings: SimpleNamespace, **claims: object) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": "12345678-1234-5678-1234-567812345678",
        "username": "alice",
        "exp": now + timedelta(hours=1),
        "iat": now,
        **claims,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


class TestDecodeUserFromRequest:
    """The shared JWT helper backs both get_current_user variants."""

    def test_returns_none_for_missing_header(self) -> None:
        assert _decode_user_from_request(_build_request(None), _build_settings()) is None

    def test_returns_none_for_non_bearer_scheme(self) -> None:
        assert _decode_user_from_request(_build_request("Basic dXNlcjpwdw=="), _build_settings()) is None

    def test_returns_none_when_github_orgs_claim_missing(self) -> None:
        settings = _build_settings()
        token = _mint(settings)  # no github_orgs
        request = _build_request(f"Bearer {token}")
        assert _decode_user_from_request(request, settings) is None

    def test_returns_user_when_token_valid(self) -> None:
        settings = _build_settings()
        token = _mint(settings, github_orgs=["my-org", "other"])
        user = _decode_user_from_request(_build_request(f"Bearer {token}"), settings)
        assert user is not None
        assert user.username == "alice"
        assert user.github_orgs == ("my-org", "other")

    def test_propagates_jwterror_for_bad_signature(self) -> None:
        good = _build_settings("good-secret-1234567890")
        bad = _build_settings("bad-secret-9876543210")
        token = _mint(good, github_orgs=["x"])
        with pytest.raises(JWTError):
            _decode_user_from_request(_build_request(f"Bearer {token}"), bad)


class TestGetCurrentUserOptional:
    """Anonymous + invalid tokens both yield None without raising."""

    def test_returns_none_on_missing_header(self) -> None:
        assert get_current_user_optional(_build_request(None), _build_settings()) is None

    def test_returns_none_on_invalid_signature(self) -> None:
        good = _build_settings("good-secret-1234567890")
        bad = _build_settings("bad-secret-9876543210")
        token = _mint(good, github_orgs=["x"])
        assert get_current_user_optional(_build_request(f"Bearer {token}"), bad) is None


class TestGetCurrentUser:
    """The strict variant must reject anything that isn't a fresh, signed token."""

    def test_raises_401_on_missing_header(self) -> None:
        with pytest.raises(HTTPException) as exc:
            get_current_user(_build_request(None), _build_settings())
        assert exc.value.status_code == 401

    def test_raises_401_on_invalid_signature(self) -> None:
        good = _build_settings("good-secret-1234567890")
        bad = _build_settings("bad-secret-9876543210")
        token = _mint(good, github_orgs=["x"])
        with pytest.raises(HTTPException) as exc:
            get_current_user(_build_request(f"Bearer {token}"), bad)
        assert exc.value.status_code == 401

    def test_raises_401_for_pre_org_refactor_token(self) -> None:
        settings = _build_settings()
        token = _mint(settings)  # no github_orgs claim
        with pytest.raises(HTTPException) as exc:
            get_current_user(_build_request(f"Bearer {token}"), settings)
        assert exc.value.status_code == 401
        assert "outdated" in exc.value.detail


class TestStaleTokenDetection:
    def test_token_without_github_orgs_returns_401(self, test_settings, client):
        """A JWT missing the github_orgs claim should be rejected as stale."""
        # Manually craft a token without the github_orgs claim
        now = datetime.now(UTC)
        payload = {
            "sub": "12345678-1234-5678-1234-567812345678",
            "username": "olduser",
            "exp": now + timedelta(hours=1),
            "iat": now,
        }
        stale_token = jwt.encode(
            payload,
            test_settings.jwt_secret,
            algorithm=test_settings.jwt_algorithm,
        )

        resp = client.get(
            "/v1/orgs",
            headers={"Authorization": f"Bearer {stale_token}"},
        )

        assert resp.status_code == 401
        assert "outdated" in resp.json()["detail"]
        assert "dhub login" in resp.json()["detail"]

    def test_token_with_github_orgs_passes(self, test_settings, client):
        """A JWT containing the github_orgs claim should pass auth."""
        now = datetime.now(UTC)
        payload = {
            "sub": "12345678-1234-5678-1234-567812345678",
            "username": "newuser",
            "github_orgs": ["my-org"],
            "exp": now + timedelta(hours=1),
            "iat": now,
        }
        token = jwt.encode(
            payload,
            test_settings.jwt_secret,
            algorithm=test_settings.jwt_algorithm,
        )

        resp = client.get(
            "/v1/orgs",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Should not be 401 — the request passes auth
        assert resp.status_code != 401

    def test_token_with_empty_github_orgs_passes(self, test_settings, client):
        """A JWT with an empty github_orgs list is valid (claim is present)."""
        now = datetime.now(UTC)
        payload = {
            "sub": "12345678-1234-5678-1234-567812345678",
            "username": "solouser",
            "github_orgs": [],
            "exp": now + timedelta(hours=1),
            "iat": now,
        }
        token = jwt.encode(
            payload,
            test_settings.jwt_secret,
            algorithm=test_settings.jwt_algorithm,
        )

        resp = client.get(
            "/v1/orgs",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code != 401
