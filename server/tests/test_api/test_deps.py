"""Tests for stale token detection in get_current_user, plus shared helpers."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException
from jose import jwt

from decision_hub.api.deps import parse_uuid, require_visible_skill
from tests.factories import make_org, make_skill


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


class TestParseUuid:
    """The shared helper that both registry and tracker routes now use."""

    def test_valid_uuid_parses(self) -> None:
        raw = "12345678-1234-5678-1234-567812345678"

        assert parse_uuid(raw, "run_id") == UUID(raw)

    def test_invalid_uuid_raises_422_with_field_name(self) -> None:
        with pytest.raises(HTTPException) as exc:
            parse_uuid("not-a-uuid", "run_id")

        assert exc.value.status_code == 422
        # The field name is in the detail so the API caller can distinguish
        # which parameter was malformed.
        assert "run_id" in exc.value.detail

    def test_empty_string_raises_422(self) -> None:
        with pytest.raises(HTTPException) as exc:
            parse_uuid("", "tracker_id")

        assert exc.value.status_code == 422


class TestRequireVisibleSkill:
    """The extracted skill-lookup helper.

    Formerly the same three lines (``list_user_org_ids`` + ``find_skill_by_slug``
    + ``HTTPException(404)`` with a copy-pasted message) at five sites in
    ``registry_routes.py``.  Centralising it also guards against a future
    handler forgetting the ``user_org_ids`` kwarg, which would silently omit
    private skills the caller is entitled to see.
    """

    def _fake_user(self) -> object:
        return type("U", (), {"id": UUID("12345678-1234-5678-1234-567812345678")})()

    @patch("decision_hub.api.deps.find_skill_by_slug")
    @patch("decision_hub.api.deps.list_user_org_ids")
    def test_returns_skill_and_user_org_ids_when_authenticated(
        self, mock_list_orgs: MagicMock, mock_find_skill: MagicMock
    ) -> None:
        org = make_org()
        skill = make_skill(org)
        mock_list_orgs.return_value = [org.id]
        mock_find_skill.return_value = skill
        conn = MagicMock()

        result_skill, user_org_ids = require_visible_skill(
            conn, org_slug="test-org", skill_name="my-skill", user=self._fake_user()
        )

        assert result_skill is skill
        assert user_org_ids == [org.id]
        # Critical: the user_org_ids must be threaded into the visibility filter.
        mock_find_skill.assert_called_once_with(conn, "test-org", "my-skill", user_org_ids=[org.id])

    @patch("decision_hub.api.deps.find_skill_by_slug")
    @patch("decision_hub.api.deps.list_user_org_ids")
    def test_passes_none_user_org_ids_when_anonymous(
        self, mock_list_orgs: MagicMock, mock_find_skill: MagicMock
    ) -> None:
        mock_find_skill.return_value = make_skill(make_org())
        conn = MagicMock()

        _, user_org_ids = require_visible_skill(conn, "test-org", "my-skill", user=None)

        assert user_org_ids is None
        # Anonymous callers must never trigger a membership lookup.
        mock_list_orgs.assert_not_called()
        mock_find_skill.assert_called_once_with(conn, "test-org", "my-skill", user_org_ids=None)

    @patch("decision_hub.api.deps.find_skill_by_slug")
    def test_raises_404_when_skill_not_visible(self, mock_find_skill: MagicMock) -> None:
        mock_find_skill.return_value = None

        with pytest.raises(HTTPException) as exc:
            require_visible_skill(MagicMock(), "test-org", "private-skill", user=None)

        assert exc.value.status_code == 404
        # Same message whether the skill exists-but-private or truly missing —
        # avoids leaking existence of private skills to non-members.
        assert "private-skill" in exc.value.detail
        assert "test-org" in exc.value.detail
