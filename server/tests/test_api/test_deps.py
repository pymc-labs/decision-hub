"""Tests for stale token detection in get_current_user."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from jose import jwt

from decision_hub.api.deps import (
    _AuthFailure,
    _decode_bearer,
    get_current_user,
    get_current_user_optional,
)


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


def _make_request(auth_header: str | None = None) -> MagicMock:
    """Mock Request with a configurable Authorization header."""
    request = MagicMock()
    request.client.host = "10.0.0.1"
    request.headers = MagicMock()
    request.headers.get.side_effect = lambda name, default=None: auth_header if name == "Authorization" else default
    return request


def _test_settings() -> SimpleNamespace:
    return SimpleNamespace(
        jwt_secret="shared-secret-for-decode-bearer",
        jwt_algorithm="HS256",
    )


def _issue_token(settings: SimpleNamespace, *, include_orgs: bool = True) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": "12345678-1234-5678-1234-567812345678",
        "username": "alice",
        "exp": now + timedelta(hours=1),
        "iat": now,
    }
    if include_orgs:
        payload["github_orgs"] = ["acme"]
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


class TestDecodeBearer:
    """Unit tests for the shared bearer-token decoder.

    ``_decode_bearer`` is the single code path both auth dependencies
    use; testing it directly guarantees that the 401-raising and
    None-returning variants stay in lock-step.
    """

    def test_raises_when_header_missing(self) -> None:
        with pytest.raises(_AuthFailure) as exc:
            _decode_bearer(_make_request(None), _test_settings())
        assert "authorization" in exc.value.message.lower()
        assert not exc.value.outdated

    def test_raises_when_header_has_wrong_scheme(self) -> None:
        with pytest.raises(_AuthFailure):
            _decode_bearer(_make_request("Basic abc"), _test_settings())

    def test_raises_on_invalid_signature(self) -> None:
        settings = _test_settings()
        good = _issue_token(settings)
        with pytest.raises(_AuthFailure) as exc:
            _decode_bearer(
                _make_request(f"Bearer {good}"),
                SimpleNamespace(jwt_secret="other", jwt_algorithm="HS256"),
            )
        assert exc.value.message == "Invalid token"
        assert not exc.value.outdated

    def test_flags_outdated_token_missing_github_orgs(self) -> None:
        settings = _test_settings()
        stale = _issue_token(settings, include_orgs=False)
        with pytest.raises(_AuthFailure) as exc:
            _decode_bearer(_make_request(f"Bearer {stale}"), settings)
        assert exc.value.outdated
        assert "dhub login" in exc.value.message

    def test_returns_user_on_valid_token(self) -> None:
        settings = _test_settings()
        token = _issue_token(settings)
        user = _decode_bearer(_make_request(f"Bearer {token}"), settings)
        assert user.username == "alice"
        assert user.github_orgs == ("acme",)


class TestCurrentUserDeps:
    """Behavioural tests guaranteeing the 401 and None variants stay aligned."""

    def test_required_dep_maps_failure_to_401(self) -> None:
        request = _make_request(None)
        with pytest.raises(HTTPException) as exc:
            get_current_user(request, _test_settings())
        assert exc.value.status_code == 401

    def test_optional_dep_returns_none_on_failure(self) -> None:
        request = _make_request(None)
        assert get_current_user_optional(request, _test_settings()) is None

    def test_both_return_same_user_on_success(self) -> None:
        settings = _test_settings()
        token = _issue_token(settings)
        req_a = _make_request(f"Bearer {token}")
        req_b = _make_request(f"Bearer {token}")
        required = get_current_user(req_a, settings)
        optional = get_current_user_optional(req_b, settings)
        assert optional is not None
        assert (required.id, required.username, required.github_orgs) == (
            optional.id,
            optional.username,
            optional.github_orgs,
        )
