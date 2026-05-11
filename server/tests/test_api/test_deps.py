"""Tests for stale token detection in get_current_user."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from jose import jwt

from decision_hub.api.deps import _decode_bearer_user, get_current_user_optional
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


class TestBearerDecoder:
    """Unit tests for the shared ``_decode_bearer_user`` helper.

    The required (``get_current_user``) and optional
    (``get_current_user_optional``) deps both delegate JWT parsing to
    this helper. Covering it directly avoids re-encoding the same
    edge cases in two places.
    """

    def _settings(self, jwt_secret: str) -> SimpleNamespace:
        return SimpleNamespace(jwt_secret=jwt_secret, jwt_algorithm="HS256")

    def _request(self, token: str | None) -> MagicMock:
        request = MagicMock()
        request.headers = {"Authorization": f"Bearer {token}"} if token else {}
        return request

    def test_returns_none_on_missing_header(self, jwt_secret: str) -> None:
        assert _decode_bearer_user(self._request(None), self._settings(jwt_secret)) is None

    def test_returns_none_on_invalid_token(self, jwt_secret: str) -> None:
        assert _decode_bearer_user(self._request("not-a-jwt"), self._settings(jwt_secret)) is None

    def test_returns_none_on_pre_orgs_token(self, jwt_secret: str) -> None:
        """Tokens missing the ``github_orgs`` claim are rejected as stale."""
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": "12345678-1234-5678-1234-567812345678",
                "username": "olduser",
                "exp": now + timedelta(hours=1),
                "iat": now,
            },
            jwt_secret,
            algorithm="HS256",
        )
        assert _decode_bearer_user(self._request(token), self._settings(jwt_secret)) is None

    def test_returns_user_on_valid_token(self, jwt_secret: str) -> None:
        token = create_jwt(
            user_id="12345678-1234-5678-1234-567812345678",
            username="alice",
            secret=jwt_secret,
            github_orgs=["acme"],
        )
        user = _decode_bearer_user(self._request(token), self._settings(jwt_secret))
        assert user is not None
        assert user.username == "alice"
        assert user.github_orgs == ("acme",)


class TestGetCurrentUserOptional:
    """Optional-auth wrapper must never raise and must return None on bad input."""

    def test_no_header_returns_none(self, jwt_secret: str) -> None:
        request = MagicMock()
        request.headers = {}
        assert get_current_user_optional(request, SimpleNamespace(jwt_secret=jwt_secret, jwt_algorithm="HS256")) is None

    def test_bad_token_returns_none(self, jwt_secret: str) -> None:
        request = MagicMock()
        request.headers = {"Authorization": "Bearer garbage"}
        assert get_current_user_optional(request, SimpleNamespace(jwt_secret=jwt_secret, jwt_algorithm="HS256")) is None

    def test_valid_token_returns_user(self, jwt_secret: str) -> None:
        token = create_jwt(
            user_id="12345678-1234-5678-1234-567812345678",
            username="bob",
            secret=jwt_secret,
            github_orgs=[],
        )
        request = MagicMock()
        request.headers = {"Authorization": f"Bearer {token}"}
        user = get_current_user_optional(request, SimpleNamespace(jwt_secret=jwt_secret, jwt_algorithm="HS256"))
        assert user is not None
        assert user.username == "bob"
