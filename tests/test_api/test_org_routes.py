"""Tests for decision_hub.api.org_routes -- organisation management endpoints."""

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from decision_hub.models import Organization, OrgInvite, OrgMember


class TestCreateOrganisation:
    """POST /v1/orgs -- create a new organisation."""

    @patch("decision_hub.api.org_routes.insert_org_member")
    @patch("decision_hub.api.org_routes.insert_organization")
    def test_create_org_success(
        self,
        mock_insert_org: MagicMock,
        mock_insert_member: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Should create an org and register the caller as owner."""
        org_id = UUID("aaaaaaaa-0000-0000-0000-000000000001")
        mock_insert_org.return_value = Organization(
            id=org_id, slug="my-org", owner_id=sample_user_id,
        )
        mock_insert_member.return_value = OrgMember(
            org_id=org_id, user_id=sample_user_id, role="owner",
        )

        resp = client.post(
            "/v1/orgs",
            json={"slug": "my-org"},
            headers=auth_headers,
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["slug"] == "my-org"
        assert data["id"] == str(org_id)

    def test_create_org_invalid_slug(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """An invalid slug should raise ValueError from the domain validation."""
        with pytest.raises(ValueError, match="Invalid org slug"):
            client.post(
                "/v1/orgs",
                json={"slug": "INVALID SLUG!"},
                headers=auth_headers,
            )

    def test_create_org_unauthenticated(self, client: TestClient) -> None:
        """Missing auth header should return 401."""
        resp = client.post("/v1/orgs", json={"slug": "my-org"})
        assert resp.status_code == 401


class TestListOrgs:
    """GET /v1/orgs -- list user's organisations."""

    @patch("decision_hub.api.org_routes.list_user_orgs")
    def test_list_orgs(
        self,
        mock_list: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Should return the organisations the user belongs to."""
        mock_list.return_value = [
            Organization(
                id=UUID("aaaaaaaa-0000-0000-0000-000000000001"),
                slug="org-one",
                owner_id=sample_user_id,
            ),
            Organization(
                id=UUID("aaaaaaaa-0000-0000-0000-000000000002"),
                slug="org-two",
                owner_id=sample_user_id,
            ),
        ]

        resp = client.get("/v1/orgs", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["slug"] == "org-one"
        assert data[1]["slug"] == "org-two"


class TestInviteUser:
    """POST /v1/orgs/{slug}/invites -- invite a user to an org."""

    @patch("decision_hub.api.org_routes.insert_org_invite")
    @patch("decision_hub.api.org_routes.find_org_member")
    @patch("decision_hub.api.org_routes.find_org_by_slug")
    def test_invite_success(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_insert_invite: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """An owner should be able to invite a user."""
        org_id = UUID("aaaaaaaa-0000-0000-0000-000000000001")
        invite_id = UUID("bbbbbbbb-0000-0000-0000-000000000001")

        mock_find_org.return_value = Organization(
            id=org_id, slug="my-org", owner_id=sample_user_id,
        )
        mock_find_member.return_value = OrgMember(
            org_id=org_id, user_id=sample_user_id, role="owner",
        )
        mock_insert_invite.return_value = OrgInvite(
            id=invite_id, org_id=org_id,
            invitee_github_username="newuser", status="pending",
        )

        resp = client.post(
            "/v1/orgs/my-org/invites",
            json={"github_username": "newuser", "role": "member"},
            headers=auth_headers,
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"

    @patch("decision_hub.api.org_routes.find_org_member")
    @patch("decision_hub.api.org_routes.find_org_by_slug")
    def test_invite_forbidden_for_member_role(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """A regular member should not be able to invite."""
        org_id = UUID("aaaaaaaa-0000-0000-0000-000000000001")

        mock_find_org.return_value = Organization(
            id=org_id, slug="my-org", owner_id=sample_user_id,
        )
        mock_find_member.return_value = OrgMember(
            org_id=org_id, user_id=sample_user_id, role="member",
        )

        resp = client.post(
            "/v1/orgs/my-org/invites",
            json={"github_username": "newuser", "role": "member"},
            headers=auth_headers,
        )

        assert resp.status_code == 403

    @patch("decision_hub.api.org_routes.find_org_by_slug")
    def test_invite_org_not_found(
        self,
        mock_find_org: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Inviting into a non-existent org should return 404."""
        mock_find_org.return_value = None

        resp = client.post(
            "/v1/orgs/no-such-org/invites",
            json={"github_username": "someone", "role": "member"},
            headers=auth_headers,
        )

        assert resp.status_code == 404
