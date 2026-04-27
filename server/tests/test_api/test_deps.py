"""Tests for the auth dependencies in ``decision_hub.api.deps``.

Covers both end-to-end behaviour through the test client and the shared
``_user_from_jwt`` parser used by both ``get_current_user`` (raises 401)
and ``get_current_user_optional`` (returns None).
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from jose import jwt

from decision_hub.api.deps import _JWTReason, _user_from_jwt


def _request_with_header(value: str | None) -> MagicMock:
    request = MagicMock()
    request.headers = {"Authorization": value} if value is not None else {}
    request.client.host = "127.0.0.1"
    return request


def _settings(secret: str = "shared-secret") -> SimpleNamespace:
    return SimpleNamespace(jwt_secret=secret, jwt_algorithm="HS256")


class TestUserFromJwt:
    """Unit tests for the shared ``_user_from_jwt`` helper."""

    def test_missing_header_returns_missing(self) -> None:
        request = _request_with_header(None)
        user, reason = _user_from_jwt(request, _settings())
        assert user is None
        assert reason == _JWTReason.MISSING

    def test_non_bearer_header_returns_missing(self) -> None:
        request = _request_with_header("Basic abc123")
        user, reason = _user_from_jwt(request, _settings())
        assert user is None
        assert reason == _JWTReason.MISSING

    def test_invalid_signature_returns_invalid(self) -> None:
        # Token signed with a different secret than _settings().
        token = jwt.encode(
            {
                "sub": "12345678-1234-5678-1234-567812345678",
                "username": "x",
                "github_orgs": [],
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            "wrong-secret",
            algorithm="HS256",
        )
        request = _request_with_header(f"Bearer {token}")
        user, reason = _user_from_jwt(request, _settings())
        assert user is None
        assert reason == _JWTReason.INVALID

    def test_missing_github_orgs_claim_returns_outdated(self) -> None:
        token = jwt.encode(
            {
                "sub": "12345678-1234-5678-1234-567812345678",
                "username": "olduser",
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            "shared-secret",
            algorithm="HS256",
        )
        request = _request_with_header(f"Bearer {token}")
        user, reason = _user_from_jwt(request, _settings())
        assert user is None
        assert reason == _JWTReason.OUTDATED

    def test_valid_token_returns_user_and_no_reason(self) -> None:
        token = jwt.encode(
            {
                "sub": "12345678-1234-5678-1234-567812345678",
                "username": "alice",
                "github_orgs": ["acme", "widgets"],
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            "shared-secret",
            algorithm="HS256",
        )
        request = _request_with_header(f"Bearer {token}")
        user, reason = _user_from_jwt(request, _settings())
        assert reason is None
        assert user is not None
        assert user.username == "alice"
        assert user.github_orgs == ("acme", "widgets")


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
