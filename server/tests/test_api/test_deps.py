"""Tests for JWT-based auth dependencies (strict + optional)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import HTTPException
from jose import jwt

from decision_hub.api.deps import (
    _parse_bearer_token,
    _StaleTokenError,
    _user_from_jwt,
    get_current_user,
    get_current_user_optional,
)
from decision_hub.domain.auth import create_jwt


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


class TestBearerTokenParsing:
    """`_parse_bearer_token` is the single header-parsing implementation."""

    @staticmethod
    def _req(auth: str | None) -> MagicMock:
        request = MagicMock()
        request.headers = {"Authorization": auth} if auth is not None else {}
        return request

    def test_none_when_header_missing(self) -> None:
        assert _parse_bearer_token(self._req(None)) is None

    def test_none_when_scheme_is_not_bearer(self) -> None:
        assert _parse_bearer_token(self._req("Basic abc123")) is None

    def test_returns_token_when_bearer(self) -> None:
        assert _parse_bearer_token(self._req("Bearer abc123")) == "abc123"


class TestUserFromJwt:
    """`_user_from_jwt` centralises decoding + user reconstruction."""

    def _settings(self) -> MagicMock:
        settings = MagicMock()
        settings.jwt_secret = "test-secret-that-is-long-enough"
        settings.jwt_algorithm = "HS256"
        return settings

    def test_returns_user_for_valid_token(self) -> None:
        settings = self._settings()
        token = create_jwt(
            user_id="12345678-1234-5678-1234-567812345678",
            username="alice",
            secret=settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
            expiry_hours=1,
            github_orgs=["myorg"],
        )

        user = _user_from_jwt(token, settings)

        assert user.id == UUID("12345678-1234-5678-1234-567812345678")
        assert user.username == "alice"
        assert user.github_orgs == ("myorg",)

    def test_raises_stale_when_github_orgs_missing(self) -> None:
        settings = self._settings()
        now = datetime.now(UTC)
        stale_token = jwt.encode(
            {
                "sub": "12345678-1234-5678-1234-567812345678",
                "username": "olduser",
                "exp": now + timedelta(hours=1),
                "iat": now,
            },
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

        with pytest.raises(_StaleTokenError):
            _user_from_jwt(stale_token, settings)


class TestOptionalMirrorsStrictOnHappyPath:
    """Refactor guard: for a valid token, both dependencies return the SAME User."""

    def test_matching_user(self, test_settings) -> None:
        request = MagicMock()
        token = create_jwt(
            user_id="12345678-1234-5678-1234-567812345678",
            username="alice",
            secret=test_settings.jwt_secret,
            algorithm=test_settings.jwt_algorithm,
            expiry_hours=1,
            github_orgs=["myorg"],
        )
        request.headers = {"Authorization": f"Bearer {token}"}

        strict = get_current_user(request, test_settings)
        optional = get_current_user_optional(request, test_settings)

        assert strict == optional

    def test_missing_header_diverges(self, test_settings) -> None:
        request = MagicMock()
        request.headers = {}
        request.client.host = "127.0.0.1"

        with pytest.raises(HTTPException):
            get_current_user(request, test_settings)

        assert get_current_user_optional(request, test_settings) is None

    def test_stale_token_diverges(self, test_settings) -> None:
        request = MagicMock()
        request.client.host = "127.0.0.1"
        now = datetime.now(UTC)
        stale_token = jwt.encode(
            {
                "sub": "12345678-1234-5678-1234-567812345678",
                "username": "olduser",
                "exp": now + timedelta(hours=1),
                "iat": now,
            },
            test_settings.jwt_secret,
            algorithm=test_settings.jwt_algorithm,
        )
        request.headers = {"Authorization": f"Bearer {stale_token}"}

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(request, test_settings)
        assert exc_info.value.status_code == 401
        assert "outdated" in exc_info.value.detail

        assert get_current_user_optional(request, test_settings) is None
