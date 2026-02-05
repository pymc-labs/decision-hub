"""Tests for decision_hub.api.registry_routes -- publish and resolve endpoints."""

import json
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from decision_hub.models import Organization, OrgMember, Skill, Version


# ---------------------------------------------------------------------------
# Shared test data helpers
# ---------------------------------------------------------------------------

SAMPLE_USER_ID = UUID("12345678-1234-5678-1234-567812345678")


def _make_org(owner_id: UUID = SAMPLE_USER_ID) -> Organization:
    return Organization(id=uuid4(), slug="test-org", owner_id=owner_id)


def _make_member(org: Organization, user_id: UUID = SAMPLE_USER_ID) -> OrgMember:
    return OrgMember(org_id=org.id, user_id=user_id, role="owner")


def _make_skill(org: Organization, name: str = "my-skill") -> Skill:
    return Skill(id=uuid4(), org_id=org.id, name=name)


def _make_version(skill: Skill, semver: str = "1.0.0") -> Version:
    return Version(
        id=uuid4(),
        skill_id=skill.id,
        semver=semver,
        s3_key=f"skills/test-org/{skill.name}/{semver}.zip",
        checksum="abc123def456",
        runtime_config=None,
        eval_status="pending",
    )


def _publish_request(
    client: TestClient,
    headers: dict[str, str],
    org_slug: str = "test-org",
    skill_name: str = "my-skill",
    version: str = "1.0.0",
) -> ...:
    """Send a POST /v1/publish request with standard multipart form data."""
    metadata = json.dumps({
        "org_slug": org_slug,
        "skill_name": skill_name,
        "version": version,
    })
    return client.post(
        "/v1/publish",
        data={"metadata": metadata},
        files={"zip_file": ("skill.zip", b"fake-zip-bytes", "application/zip")},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# POST /v1/publish
# ---------------------------------------------------------------------------

class TestPublishSkill:
    """POST /v1/publish -- publish a new skill version."""

    @patch("decision_hub.api.registry_routes.insert_version")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_routes.upload_skill_zip")
    @patch("decision_hub.api.registry_routes.compute_checksum")
    @patch("decision_hub.api.registry_routes.find_org_member")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    def test_publish_success(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_checksum: MagicMock,
        mock_upload: MagicMock,
        mock_find_skill: MagicMock,
        mock_insert_version: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Full publish flow: org exists, user is member, skill exists."""
        org = _make_org(sample_user_id)
        skill = _make_skill(org)
        version = _make_version(skill)

        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org, sample_user_id)
        mock_checksum.return_value = "abc123def456"
        mock_find_skill.return_value = skill
        mock_insert_version.return_value = version

        resp = _publish_request(client, auth_headers)

        assert resp.status_code == 201
        data = resp.json()
        assert data["skill_id"] == str(skill.id)
        assert data["version"] == "1.0.0"
        assert data["s3_key"] == f"skills/test-org/my-skill/1.0.0.zip"
        assert data["checksum"] == "abc123def456"

        # Verify S3 upload was called with the right arguments
        mock_upload.assert_called_once_with(
            client.app.state.s3_client,
            "test-bucket",
            "skills/test-org/my-skill/1.0.0.zip",
            b"fake-zip-bytes",
        )

    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    def test_publish_org_not_found(
        self,
        mock_find_org: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Publishing to a non-existent org should return 404."""
        mock_find_org.return_value = None

        resp = _publish_request(client, auth_headers, org_slug="no-such-org")

        assert resp.status_code == 404
        assert "Organisation not found" in resp.json()["detail"]

    @patch("decision_hub.api.registry_routes.find_org_member")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    def test_publish_not_member(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Publishing when user is not an org member should return 403."""
        org = _make_org(sample_user_id)
        mock_find_org.return_value = org
        mock_find_member.return_value = None

        resp = _publish_request(client, auth_headers)

        assert resp.status_code == 403
        assert "not a member" in resp.json()["detail"]

    def test_publish_no_auth(self, client: TestClient) -> None:
        """Publishing without auth should return 401."""
        metadata = json.dumps({
            "org_slug": "test-org",
            "skill_name": "my-skill",
            "version": "1.0.0",
        })
        resp = client.post(
            "/v1/publish",
            data={"metadata": metadata},
            files={"zip_file": ("skill.zip", b"fake-zip-bytes", "application/zip")},
        )

        assert resp.status_code == 401

    @patch("decision_hub.api.registry_routes.insert_version")
    @patch("decision_hub.api.registry_routes.insert_skill")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_routes.upload_skill_zip")
    @patch("decision_hub.api.registry_routes.compute_checksum")
    @patch("decision_hub.api.registry_routes.find_org_member")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    def test_publish_creates_new_skill(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_checksum: MagicMock,
        mock_upload: MagicMock,
        mock_find_skill: MagicMock,
        mock_insert_skill: MagicMock,
        mock_insert_version: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """When skill doesn't exist yet, it should be created via insert_skill."""
        org = _make_org(sample_user_id)
        new_skill = _make_skill(org, name="brand-new-skill")
        version = _make_version(new_skill)

        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org, sample_user_id)
        mock_checksum.return_value = "abc123def456"
        mock_find_skill.return_value = None  # skill does not exist yet
        mock_insert_skill.return_value = new_skill
        mock_insert_version.return_value = version

        resp = _publish_request(
            client, auth_headers, skill_name="brand-new-skill",
        )

        assert resp.status_code == 201
        mock_insert_skill.assert_called_once_with(
            mock_find_org.call_args[0][0],  # the conn argument
            org.id,
            "brand-new-skill",
        )
        assert resp.json()["skill_id"] == str(new_skill.id)


# ---------------------------------------------------------------------------
# GET /v1/resolve/{org_slug}/{skill_name}
# ---------------------------------------------------------------------------

class TestResolveSkill:
    """GET /v1/resolve/{org_slug}/{skill_name} -- resolve a skill version."""

    @patch("decision_hub.api.registry_routes.generate_presigned_url")
    @patch("decision_hub.api.registry_routes.resolve_version")
    def test_resolve_success(
        self,
        mock_resolve: MagicMock,
        mock_presign: MagicMock,
        client: TestClient,
    ) -> None:
        """Resolving latest should return version info and a download URL."""
        org = _make_org()
        skill = _make_skill(org)
        version = _make_version(skill, semver="2.1.0")

        mock_resolve.return_value = version
        mock_presign.return_value = "https://s3.example.com/presigned-url"

        resp = client.get("/v1/resolve/test-org/my-skill?spec=latest")

        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "2.1.0"
        assert data["download_url"] == "https://s3.example.com/presigned-url"
        assert data["checksum"] == version.checksum

    @patch("decision_hub.api.registry_routes.resolve_version")
    def test_resolve_not_found(
        self,
        mock_resolve: MagicMock,
        client: TestClient,
    ) -> None:
        """Resolving a non-existent version should return 404."""
        mock_resolve.return_value = None

        resp = client.get("/v1/resolve/test-org/my-skill?spec=latest")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    @patch("decision_hub.api.registry_routes.generate_presigned_url")
    @patch("decision_hub.api.registry_routes.resolve_version")
    def test_resolve_with_specific_version(
        self,
        mock_resolve: MagicMock,
        mock_presign: MagicMock,
        client: TestClient,
    ) -> None:
        """Resolving with an exact semver spec should pass it through."""
        org = _make_org()
        skill = _make_skill(org)
        version = _make_version(skill, semver="1.2.3")

        mock_resolve.return_value = version
        mock_presign.return_value = "https://s3.example.com/v1.2.3"

        resp = client.get("/v1/resolve/test-org/my-skill?spec=1.2.3")

        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "1.2.3"
        assert data["download_url"] == "https://s3.example.com/v1.2.3"

        # Verify resolve_version was called with the exact spec
        mock_resolve.assert_called_once()
        call_args = mock_resolve.call_args
        assert call_args[0][1] == "test-org"  # org_slug
        assert call_args[0][2] == "my-skill"  # skill_name
        assert call_args[0][3] == "1.2.3"  # spec

    @patch("decision_hub.api.registry_routes.generate_presigned_url")
    @patch("decision_hub.api.registry_routes.resolve_version")
    def test_resolve_does_not_require_auth(
        self,
        mock_resolve: MagicMock,
        mock_presign: MagicMock,
        client: TestClient,
    ) -> None:
        """Resolve endpoint should work without authentication headers."""
        org = _make_org()
        skill = _make_skill(org)
        version = _make_version(skill)

        mock_resolve.return_value = version
        mock_presign.return_value = "https://s3.example.com/public"

        # No auth_headers -- should still succeed
        resp = client.get("/v1/resolve/test-org/my-skill")

        assert resp.status_code == 200
