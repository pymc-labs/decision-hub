"""Tests for private skill visibility and access grant endpoints."""

from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from decision_hub.models import Organization, OrgMember, Skill, SkillAccessGrant

# ---------------------------------------------------------------------------
# Shared test data helpers
# ---------------------------------------------------------------------------

SAMPLE_USER_ID = UUID("12345678-1234-5678-1234-567812345678")


def _make_org(owner_id: UUID = SAMPLE_USER_ID, slug: str = "test-org") -> Organization:
    return Organization(id=uuid4(), slug=slug, owner_id=owner_id)


def _make_member(org: Organization, user_id: UUID = SAMPLE_USER_ID) -> OrgMember:
    return OrgMember(org_id=org.id, user_id=user_id, role="owner")


def _make_skill(
    org: Organization,
    name: str = "my-skill",
    description: str = "A test skill",
    visibility: str = "public",
) -> Skill:
    return Skill(id=uuid4(), org_id=org.id, name=name, description=description, visibility=visibility)


# ---------------------------------------------------------------------------
# PUT /v1/skills/{org}/{skill}/visibility
# ---------------------------------------------------------------------------


class TestChangeVisibility:
    """PUT /v1/skills/{org_slug}/{skill_name}/visibility"""

    @patch("decision_hub.api.registry_routes.update_skill_visibility")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_change_visibility_to_org(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        mock_update_vis: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        org = _make_org()
        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org)
        mock_find_skill.return_value = _make_skill(org)

        resp = client.put(
            "/v1/skills/test-org/my-skill/visibility",
            json={"visibility": "org"},
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["visibility"] == "org"
        assert data["org_slug"] == "test-org"
        assert data["skill_name"] == "my-skill"
        mock_update_vis.assert_called_once()

    @patch("decision_hub.api.registry_routes.update_skill_visibility")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_change_visibility_to_public(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        mock_update_vis: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        org = _make_org()
        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org)
        mock_find_skill.return_value = _make_skill(org, visibility="org")

        resp = client.put(
            "/v1/skills/test-org/my-skill/visibility",
            json={"visibility": "public"},
            headers=auth_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["visibility"] == "public"

    def test_change_visibility_invalid_value(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.put(
            "/v1/skills/test-org/my-skill/visibility",
            json={"visibility": "secret"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_change_visibility_skill_not_found(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        org = _make_org()
        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org)
        mock_find_skill.return_value = None

        resp = client.put(
            "/v1/skills/test-org/my-skill/visibility",
            json={"visibility": "org"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_change_visibility_non_admin_forbidden(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        org = _make_org()
        mock_find_org.return_value = org
        member = OrgMember(org_id=org.id, user_id=SAMPLE_USER_ID, role="member")
        mock_find_member.return_value = member

        resp = client.put(
            "/v1/skills/test-org/my-skill/visibility",
            json={"visibility": "org"},
            headers=auth_headers,
        )
        assert resp.status_code == 403

    def test_change_visibility_unauthenticated(
        self,
        client: TestClient,
    ) -> None:
        resp = client.put(
            "/v1/skills/test-org/my-skill/visibility",
            json={"visibility": "org"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /v1/skills/{org}/{skill}/access
# ---------------------------------------------------------------------------


class TestGrantAccess:
    """POST /v1/skills/{org_slug}/{skill_name}/access"""

    @patch("decision_hub.api.registry_routes.insert_skill_access_grant")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_grant_access_success(
        self,
        mock_service_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        mock_find_grantee_org: MagicMock,
        mock_insert_grant: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        org = _make_org()
        skill = _make_skill(org, visibility="org")
        grantee_org = _make_org(slug="partner-org")

        mock_service_find_org.return_value = org
        mock_find_member.return_value = _make_member(org)
        mock_find_skill.return_value = skill
        mock_find_grantee_org.return_value = grantee_org
        mock_insert_grant.return_value = SkillAccessGrant(
            id=uuid4(),
            skill_id=skill.id,
            grantee_org_id=grantee_org.id,
            granted_by=SAMPLE_USER_ID,
            created_at=None,
        )

        resp = client.post(
            "/v1/skills/test-org/my-skill/access",
            json={"grantee_org_slug": "partner-org"},
            headers=auth_headers,
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["grantee_org_slug"] == "partner-org"
        assert data["org_slug"] == "test-org"

    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_grant_access_skill_not_found(
        self,
        mock_service_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        org = _make_org()
        mock_service_find_org.return_value = org
        mock_find_member.return_value = _make_member(org)
        mock_find_skill.return_value = None

        resp = client.post(
            "/v1/skills/test-org/my-skill/access",
            json={"grantee_org_slug": "partner-org"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_grant_access_grantee_org_not_found(
        self,
        mock_service_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        mock_find_grantee_org: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        org = _make_org()
        mock_service_find_org.return_value = org
        mock_find_member.return_value = _make_member(org)
        mock_find_skill.return_value = _make_skill(org)
        mock_find_grantee_org.return_value = None

        resp = client.post(
            "/v1/skills/test-org/my-skill/access",
            json={"grantee_org_slug": "nonexistent"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @patch("decision_hub.api.registry_routes.insert_skill_access_grant")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_grant_access_duplicate_409(
        self,
        mock_service_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        mock_find_grantee_org: MagicMock,
        mock_insert_grant: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        from sqlalchemy.exc import IntegrityError

        org = _make_org()
        mock_service_find_org.return_value = org
        mock_find_member.return_value = _make_member(org)
        mock_find_skill.return_value = _make_skill(org)
        mock_find_grantee_org.return_value = _make_org(slug="partner-org")
        mock_insert_grant.side_effect = IntegrityError("dup", {}, None)

        resp = client.post(
            "/v1/skills/test-org/my-skill/access",
            json={"grantee_org_slug": "partner-org"},
            headers=auth_headers,
        )
        assert resp.status_code == 409

    def test_grant_access_unauthenticated(
        self,
        client: TestClient,
    ) -> None:
        resp = client.post(
            "/v1/skills/test-org/my-skill/access",
            json={"grantee_org_slug": "partner-org"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /v1/skills/{org}/{skill}/access/{grantee}
# ---------------------------------------------------------------------------


class TestRevokeAccess:
    """DELETE /v1/skills/{org_slug}/{skill_name}/access/{grantee_org_slug}"""

    @patch("decision_hub.api.registry_routes.delete_skill_access_grant")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_revoke_access_success(
        self,
        mock_service_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        mock_find_grantee_org: MagicMock,
        mock_delete_grant: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        org = _make_org()
        mock_service_find_org.return_value = org
        mock_find_member.return_value = _make_member(org)
        mock_find_skill.return_value = _make_skill(org)
        mock_find_grantee_org.return_value = _make_org(slug="partner-org")
        mock_delete_grant.return_value = True

        resp = client.delete(
            "/v1/skills/test-org/my-skill/access/partner-org",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["grantee_org_slug"] == "partner-org"

    @patch("decision_hub.api.registry_routes.delete_skill_access_grant")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_revoke_access_not_found(
        self,
        mock_service_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        mock_find_grantee_org: MagicMock,
        mock_delete_grant: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        org = _make_org()
        mock_service_find_org.return_value = org
        mock_find_member.return_value = _make_member(org)
        mock_find_skill.return_value = _make_skill(org)
        mock_find_grantee_org.return_value = _make_org(slug="partner-org")
        mock_delete_grant.return_value = False

        resp = client.delete(
            "/v1/skills/test-org/my-skill/access/partner-org",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /v1/skills/{org}/{skill}/access
# ---------------------------------------------------------------------------


class TestListAccess:
    """GET /v1/skills/{org_slug}/{skill_name}/access"""

    @patch("decision_hub.api.registry_routes.list_skill_access_grants")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_list_access_empty(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        mock_list_grants: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        org = _make_org()
        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org)
        mock_find_skill.return_value = _make_skill(org)
        mock_list_grants.return_value = []

        resp = client.get(
            "/v1/skills/test-org/my-skill/access",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /v1/skills (visibility filtering)
# ---------------------------------------------------------------------------


class TestListSkillsVisibility:
    """GET /v1/skills — verify visibility field is returned."""

    @patch("decision_hub.api.registry_routes.count_all_skills", return_value=1)
    @patch("decision_hub.api.registry_routes.list_user_org_ids")
    @patch("decision_hub.api.registry_routes.fetch_all_skills_for_index")
    def test_list_skills_returns_visibility(
        self,
        mock_fetch: MagicMock,
        mock_org_ids: MagicMock,
        mock_count: MagicMock,
        client: TestClient,
    ) -> None:
        """Public listing returns the visibility field."""
        from datetime import datetime

        mock_fetch.return_value = [
            {
                "org_slug": "test-org",
                "is_personal_org": False,
                "skill_name": "my-skill",
                "description": "desc",
                "download_count": 0,
                "visibility": "org",
                "latest_version": "1.0.0",
                "eval_status": "A",
                "created_at": datetime(2025, 1, 1),
                "published_by": "testuser",
            }
        ]

        resp = client.get("/v1/skills")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["visibility"] == "org"
