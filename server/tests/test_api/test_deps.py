"""Tests for stale token detection in get_current_user and shared helpers in deps.py."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import HTTPException
from jose import jwt

from decision_hub.api.deps import parse_uuid_param


class TestParseUuidParam:
    """Unit tests for the shared parse_uuid_param helper.

    Both registry and tracker routes used to ship their own copy of this
    function with slightly different error messages. We standardised on
    the message asserted by test_eval_logs.py — keep that contract.
    """

    def test_valid_uuid_returns_uuid_instance(self) -> None:
        value = "12345678-1234-5678-1234-567812345678"
        assert parse_uuid_param(value, "tracker_id") == UUID(value)

    def test_invalid_uuid_raises_422_with_named_field(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            parse_uuid_param("not-a-uuid", "tracker_id")
        assert exc_info.value.status_code == 422
        # The "Invalid UUID" prefix is asserted by test_eval_logs.py — must stay.
        assert "Invalid UUID" in exc_info.value.detail
        assert "tracker_id" in exc_info.value.detail
        assert "not-a-uuid" in exc_info.value.detail

    def test_empty_string_raises_422(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            parse_uuid_param("", "run_id")
        assert exc_info.value.status_code == 422


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
