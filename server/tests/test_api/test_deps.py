"""Tests for stale token detection in get_current_user."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from jose import jwt

from decision_hub.api.deps import (
    _decode_request_token,
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


# ---------------------------------------------------------------------------
# Unit-level tests for the shared _decode_request_token helper. Keeping these
# alongside the integration tests above ensures any drift between the two
# entry points (required vs optional) is caught quickly.
# ---------------------------------------------------------------------------


def _req(authorization: str | None) -> MagicMock:
    request = MagicMock()
    headers = {}
    if authorization is not None:
        headers["Authorization"] = authorization
    request.headers.get.side_effect = lambda name, default=None: headers.get(name, default)
    request.client.host = "127.0.0.1"
    return request


def _settings_with(secret: str) -> MagicMock:
    s = MagicMock()
    s.jwt_secret = secret
    s.jwt_algorithm = "HS256"
    return s


def _token(secret: str, *, with_orgs: bool = True) -> str:
    if with_orgs:
        return create_jwt(
            user_id="00000000-0000-0000-0000-000000000042",
            username="alice",
            secret=secret,
            github_orgs=["acme"],
        )
    # `create_jwt(github_orgs=None)` still writes an empty list claim, so
    # to simulate a *legacy* token (no claim at all) we encode by hand.
    now = datetime.now(UTC)
    payload = {
        "sub": "00000000-0000-0000-0000-000000000042",
        "username": "alice",
        "exp": now + timedelta(hours=1),
        "iat": now,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


class TestDecodeRequestToken:
    def test_missing_header_returns_none(self) -> None:
        assert _decode_request_token(_req(None), _settings_with("s")) is None

    def test_non_bearer_header_returns_none(self) -> None:
        assert _decode_request_token(_req("Basic xyz"), _settings_with("s")) is None

    def test_invalid_token_returns_none(self) -> None:
        assert _decode_request_token(_req("Bearer bad"), _settings_with("s")) is None

    def test_legacy_token_returns_none(self) -> None:
        secret = "x" * 32
        assert _decode_request_token(_req(f"Bearer {_token(secret, with_orgs=False)}"), _settings_with(secret)) is None

    def test_valid_token_returns_payload(self) -> None:
        secret = "x" * 32
        payload = _decode_request_token(_req(f"Bearer {_token(secret)}"), _settings_with(secret))
        assert payload is not None
        assert payload["username"] == "alice"
        assert payload["github_orgs"] == ["acme"]


class TestRequiredAndOptionalShareSemantics:
    """If the two entry points ever drift on what 'valid' means, here's where it breaks."""

    def test_required_raises_for_invalid_optional_returns_none(self) -> None:
        req = _req("Bearer garbage")
        with pytest.raises(HTTPException):
            get_current_user(req, _settings_with("s"))
        assert get_current_user_optional(req, _settings_with("s")) is None

    def test_both_accept_the_same_valid_token(self) -> None:
        secret = "x" * 32
        req = _req(f"Bearer {_token(secret)}")
        required = get_current_user(req, _settings_with(secret))
        optional = get_current_user_optional(req, _settings_with(secret))
        assert optional is not None
        assert required.username == optional.username
        assert required.github_orgs == optional.github_orgs
