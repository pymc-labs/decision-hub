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
