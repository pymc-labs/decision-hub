"""Tests for decision_hub.api.org_routes -- organisation management endpoints."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from decision_hub.models import Organization, OrgMember


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
        """An invalid slug should return 422."""
        resp = client.post(
            "/v1/orgs",
            json={"slug": "INVALID SLUG!"},
            headers=auth_headers,
        )

        assert resp.status_code == 422
        assert "Invalid org slug" in resp.json()["detail"]

    def test_create_org_unauthenticated(self, client: TestClient) -> None:
        """Missing auth header should return 401."""
        resp = client.post("/v1/orgs", json={"slug": "my-org"})
        assert resp.status_code == 401

    @patch("decision_hub.api.org_routes.insert_organization")
    def test_create_org_duplicate_slug_returns_409(
        self,
        mock_insert_org: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Duplicate org slug should return 409 instead of 500."""
        from sqlalchemy.exc import IntegrityError

        mock_insert_org.side_effect = IntegrityError(
            "duplicate key", params=None, orig=Exception(),
        )

        resp = client.post(
            "/v1/orgs",
            json={"slug": "existing-org"},
            headers=auth_headers,
        )

        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]


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

    @patch("decision_hub.api.org_routes.list_user_orgs")
    def test_list_orgs_includes_avatar_url(
        self,
        mock_list: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """OrgSummary should include avatar_url and is_personal."""
        mock_list.return_value = [
            Organization(
                id=UUID("aaaaaaaa-0000-0000-0000-000000000001"),
                slug="org-one",
                owner_id=sample_user_id,
                avatar_url="https://avatars.githubusercontent.com/u/1",
                is_personal=False,
            ),
        ]

        resp = client.get("/v1/orgs", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["avatar_url"] == "https://avatars.githubusercontent.com/u/1"
        assert data[0]["is_personal"] is False


class TestGetOrg:
    """GET /v1/orgs/{slug} -- get full org profile."""

    @patch("decision_hub.api.org_routes.find_org_by_slug")
    def test_get_org_success(
        self,
        mock_find: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Should return full org profile with GitHub metadata."""
        synced_at = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        mock_find.return_value = Organization(
            id=UUID("aaaaaaaa-0000-0000-0000-000000000001"),
            slug="pymc-labs",
            owner_id=sample_user_id,
            is_personal=False,
            avatar_url="https://avatars.githubusercontent.com/u/123",
            email="info@pymc-labs.com",
            description="Bayesian modeling",
            blog="https://pymc-labs.com",
            github_synced_at=synced_at,
        )

        resp = client.get("/v1/orgs/pymc-labs", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == "pymc-labs"
        assert data["avatar_url"] == "https://avatars.githubusercontent.com/u/123"
        assert data["email"] == "info@pymc-labs.com"
        assert data["description"] == "Bayesian modeling"
        assert data["blog"] == "https://pymc-labs.com"
        assert data["github_synced_at"] is not None

    @patch("decision_hub.api.org_routes.find_org_by_slug")
    def test_get_org_not_found(
        self,
        mock_find: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 404 for unknown org slug."""
        mock_find.return_value = None

        resp = client.get("/v1/orgs/nonexistent", headers=auth_headers)

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    def test_get_org_unauthenticated(self, client: TestClient) -> None:
        """Missing auth header should return 401."""
        resp = client.get("/v1/orgs/pymc-labs")
        assert resp.status_code == 401
