"""Tests for decision_hub.api.org_routes -- organisation management endpoints."""

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
            id=org_id,
            slug="my-org",
            owner_id=sample_user_id,
        )
        mock_insert_member.return_value = OrgMember(
            org_id=org_id,
            user_id=sample_user_id,
            role="owner",
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
            "duplicate key",
            params=None,
            orig=Exception(),
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
                is_personal=False,
                avatar_url="https://avatar/org-one",
            ),
            Organization(
                id=UUID("aaaaaaaa-0000-0000-0000-000000000002"),
                slug="org-two",
                owner_id=sample_user_id,
                is_personal=True,
                avatar_url=None,
            ),
        ]

        resp = client.get("/v1/orgs", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["slug"] == "org-one"
        assert data[0]["avatar_url"] == "https://avatar/org-one"
        assert data[0]["is_personal"] is False
        assert data[1]["slug"] == "org-two"
        assert data[1]["avatar_url"] is None
        assert data[1]["is_personal"] is True


class TestGetOrgProfile:
    """GET /v1/orgs/{slug}/profile -- public org profile."""

    @patch("decision_hub.api.org_routes.find_org_by_slug")
    def test_returns_profile(
        self,
        mock_find_org: MagicMock,
        client: TestClient,
        sample_user_id: UUID,
    ) -> None:
        """Should return public profile without auth."""
        mock_find_org.return_value = Organization(
            id=UUID("aaaaaaaa-0000-0000-0000-000000000001"),
            slug="pymc-labs",
            owner_id=sample_user_id,
            is_personal=False,
            avatar_url="https://avatars.githubusercontent.com/u/123",
            description="Bayesian stats",
            blog="https://pymc.io",
        )

        resp = client.get("/v1/orgs/pymc-labs/profile")

        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == "pymc-labs"
        assert data["is_personal"] is False
        assert data["avatar_url"] == "https://avatars.githubusercontent.com/u/123"
        assert data["description"] == "Bayesian stats"
        assert data["blog"] == "https://pymc.io"
        # Should NOT expose internal fields
        assert "id" not in data
        assert "email" not in data

    @patch("decision_hub.api.org_routes.find_org_by_slug")
    def test_returns_404_when_not_found(
        self,
        mock_find_org: MagicMock,
        client: TestClient,
    ) -> None:
        """Should return 404 when the org does not exist."""
        mock_find_org.return_value = None

        resp = client.get("/v1/orgs/ghost-org/profile")

        assert resp.status_code == 404

    @patch("decision_hub.api.org_routes.find_org_by_slug")
    def test_works_without_auth(
        self,
        mock_find_org: MagicMock,
        client: TestClient,
        sample_user_id: UUID,
    ) -> None:
        """Should succeed without any authorization headers."""
        mock_find_org.return_value = Organization(
            id=UUID("aaaaaaaa-0000-0000-0000-000000000001"),
            slug="public-org",
            owner_id=sample_user_id,
        )

        resp = client.get("/v1/orgs/public-org/profile")

        assert resp.status_code == 200
        assert resp.json()["slug"] == "public-org"


class TestGetOrg:
    """GET /v1/orgs/{slug} -- get organisation detail."""

    @patch("decision_hub.api.org_routes.find_org_member")
    @patch("decision_hub.api.org_routes.find_org_by_slug")
    def test_returns_org_detail(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Should return full org detail for a member."""
        org_id = UUID("aaaaaaaa-0000-0000-0000-000000000001")
        mock_find_org.return_value = Organization(
            id=org_id,
            slug="pymc-labs",
            owner_id=sample_user_id,
            is_personal=False,
            avatar_url="https://avatar/pymc",
            email="info@pymc.com",
            description="Bayesian stats",
            blog="https://pymc.io",
        )
        mock_find_member.return_value = OrgMember(
            org_id=org_id,
            user_id=sample_user_id,
            role="member",
        )

        resp = client.get("/v1/orgs/pymc-labs", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == "pymc-labs"
        assert data["is_personal"] is False
        assert data["avatar_url"] == "https://avatar/pymc"
        assert data["email"] == "info@pymc.com"
        assert data["description"] == "Bayesian stats"
        assert data["blog"] == "https://pymc.io"

    @patch("decision_hub.api.org_routes.find_org_by_slug")
    def test_returns_404_when_not_found(
        self,
        mock_find_org: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 404 when the org does not exist."""
        mock_find_org.return_value = None

        resp = client.get("/v1/orgs/ghost-org", headers=auth_headers)

        assert resp.status_code == 404

    @patch("decision_hub.api.org_routes.find_org_member")
    @patch("decision_hub.api.org_routes.find_org_by_slug")
    def test_returns_404_when_not_a_member(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Should return 404 when the caller is not a member (avoids leaking existence)."""
        org_id = UUID("aaaaaaaa-0000-0000-0000-000000000001")
        mock_find_org.return_value = Organization(
            id=org_id,
            slug="secret-org",
            owner_id=UUID("bbbbbbbb-0000-0000-0000-000000000001"),
        )
        mock_find_member.return_value = None

        resp = client.get("/v1/orgs/secret-org", headers=auth_headers)

        assert resp.status_code == 404

    def test_requires_auth(self, client: TestClient) -> None:
        """Should return 401 without auth headers."""
        resp = client.get("/v1/orgs/some-org")
        assert resp.status_code == 401
