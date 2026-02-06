"""Tests for decision_hub.api.registry_routes -- publish, resolve, and delete endpoints."""

import io
import json
import zipfile
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


def _make_skill(org: Organization, name: str = "my-skill", description: str = "A test skill") -> Skill:
    return Skill(id=uuid4(), org_id=org.id, name=name, description=description)


def _make_version(skill: Skill, semver: str = "1.0.0", published_by: str = "testuser") -> Version:
    return Version(
        id=uuid4(),
        skill_id=skill.id,
        semver=semver,
        s3_key=f"skills/test-org/{skill.name}/{semver}.zip",
        checksum="abc123def456",
        runtime_config=None,
        eval_status="pending",
        created_at=None,
        published_by=published_by,
    )


def _make_skill_zip(
    skill_md: str = "---\nname: my-skill\ndescription: A test skill\n---\nbody\n",
    sources: dict[str, str] | None = None,
    lockfile: str | None = None,
) -> bytes:
    """Create an in-memory zip archive with SKILL.md and optional files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", skill_md)
        for name, content in (sources or {}).items():
            zf.writestr(name, content)
        if lockfile is not None:
            zf.writestr("requirements.txt", lockfile)
    return buf.getvalue()


def _publish_request(
    client: TestClient,
    headers: dict[str, str],
    org_slug: str = "test-org",
    skill_name: str = "my-skill",
    version: str = "1.0.0",
    zip_bytes: bytes | None = None,
) -> ...:
    """Send a POST /v1/publish request with standard multipart form data."""
    metadata = json.dumps({
        "org_slug": org_slug,
        "skill_name": skill_name,
        "version": version,
    })
    if zip_bytes is None:
        zip_bytes = _make_skill_zip()
    return client.post(
        "/v1/publish",
        data={"metadata": metadata},
        files={"zip_file": ("skill.zip", zip_bytes, "application/zip")},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# POST /v1/publish
# ---------------------------------------------------------------------------

class TestPublishSkill:
    """POST /v1/publish -- publish a new skill version."""

    @patch("decision_hub.api.registry_routes.update_skill_description")
    @patch("decision_hub.api.registry_routes.insert_version")
    @patch("decision_hub.api.registry_routes.find_version")
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
        mock_find_version: MagicMock,
        mock_insert_version: MagicMock,
        mock_update_desc: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Full publish flow: org exists, user is member, skill exists, Gauntlet passes."""
        org = _make_org(sample_user_id)
        skill = _make_skill(org)
        version = _make_version(skill)

        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org, sample_user_id)
        mock_checksum.return_value = "abc123def456"
        mock_find_skill.return_value = skill
        mock_find_version.return_value = None
        mock_insert_version.return_value = version

        zip_bytes = _make_skill_zip()
        resp = _publish_request(client, auth_headers, zip_bytes=zip_bytes)

        assert resp.status_code == 201
        data = resp.json()
        assert data["skill_id"] == str(skill.id)
        assert data["version"] == "1.0.0"
        assert data["s3_key"] == "skills/test-org/my-skill/1.0.0.zip"
        assert data["checksum"] == "abc123def456"
        assert data["eval_status"] == "passed"
        # Existing skill gets its description updated
        mock_update_desc.assert_called_once()

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
            files={"zip_file": ("skill.zip", _make_skill_zip(), "application/zip")},
        )

        assert resp.status_code == 401

    @patch("decision_hub.api.registry_routes.insert_version")
    @patch("decision_hub.api.registry_routes.find_version")
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
        mock_find_version: MagicMock,
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
        mock_find_version.return_value = None
        mock_insert_version.return_value = version

        resp = _publish_request(
            client, auth_headers, skill_name="brand-new-skill",
        )

        assert resp.status_code == 201
        mock_insert_skill.assert_called_once_with(
            mock_find_org.call_args[0][0],  # the conn argument
            org.id,
            "brand-new-skill",
            "A test skill",  # description extracted from SKILL.md
        )
        assert resp.json()["skill_id"] == str(new_skill.id)

    @patch("decision_hub.api.registry_routes.find_version")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_routes.compute_checksum")
    @patch("decision_hub.api.registry_routes.find_org_member")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    def test_publish_duplicate_version(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_checksum: MagicMock,
        mock_find_skill: MagicMock,
        mock_find_version: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Publishing an already-existing version should return 409."""
        org = _make_org(sample_user_id)
        skill = _make_skill(org)
        existing_version = _make_version(skill)

        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org, sample_user_id)
        mock_checksum.return_value = "abc123def456"
        mock_find_skill.return_value = skill
        mock_find_version.return_value = existing_version

        resp = _publish_request(client, auth_headers)

        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    @patch("decision_hub.api.registry_routes.find_org_member")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    def test_publish_gauntlet_blocks_dangerous_skill(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Publish should return 422 when Gauntlet static checks fail."""
        org = _make_org(sample_user_id)
        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org, sample_user_id)

        # Zip with missing required fields in SKILL.md (no name/description)
        zip_bytes = _make_skill_zip(skill_md="# Just a heading\nNo frontmatter\n")
        resp = _publish_request(client, auth_headers, zip_bytes=zip_bytes)

        assert resp.status_code == 422
        assert "Gauntlet checks failed" in resp.json()["detail"]

    @patch("decision_hub.api.registry_routes.find_org_member")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    def test_publish_gauntlet_blocks_suspicious_code(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Publish should return 422 when safety scan detects suspicious patterns."""
        org = _make_org(sample_user_id)
        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org, sample_user_id)

        # Build dangerous source with concat to avoid hook false positives
        dangerous_code = "subprocess" + ".call(['rm', '-rf', '/'])"
        zip_bytes = _make_skill_zip(
            sources={"evil.py": dangerous_code},
        )
        resp = _publish_request(client, auth_headers, zip_bytes=zip_bytes)

        assert resp.status_code == 422
        assert "Gauntlet checks failed" in resp.json()["detail"]


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


# ---------------------------------------------------------------------------
# DELETE /v1/skills/{org_slug}/{skill_name}/{version}
# ---------------------------------------------------------------------------

class TestDeleteSkillVersion:
    """DELETE /v1/skills/{org_slug}/{skill_name}/{version} -- delete a published version."""

    @patch("decision_hub.api.registry_routes.delete_skill_zip")
    @patch("decision_hub.api.registry_routes.delete_version")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_routes.find_org_member")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    def test_delete_success(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        mock_delete_version: MagicMock,
        mock_delete_zip: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Owner can delete a version successfully."""
        org = _make_org(sample_user_id)
        skill = _make_skill(org)

        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org, sample_user_id)
        mock_find_skill.return_value = skill
        mock_delete_version.return_value = True

        resp = client.delete(
            "/v1/skills/test-org/my-skill/1.0.0",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["org_slug"] == "test-org"
        assert data["skill_name"] == "my-skill"
        assert data["version"] == "1.0.0"
        mock_delete_zip.assert_called_once()

    def test_delete_no_auth(self, client: TestClient) -> None:
        """Deleting without auth should return 401."""
        resp = client.delete("/v1/skills/test-org/my-skill/1.0.0")
        assert resp.status_code == 401

    @patch("decision_hub.api.registry_routes.find_org_member")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    def test_delete_forbidden_for_member_role(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Regular members (not owner/admin) should get 403."""
        org = _make_org(sample_user_id)
        mock_find_org.return_value = org
        mock_find_member.return_value = OrgMember(
            org_id=org.id, user_id=sample_user_id, role="member",
        )

        resp = client.delete(
            "/v1/skills/test-org/my-skill/1.0.0",
            headers=auth_headers,
        )

        assert resp.status_code == 403
        assert "owners and admins" in resp.json()["detail"]

    @patch("decision_hub.api.registry_routes.find_org_member")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    def test_delete_forbidden_for_non_member(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Non-members should get 403."""
        org = _make_org(sample_user_id)
        mock_find_org.return_value = org
        mock_find_member.return_value = None

        resp = client.delete(
            "/v1/skills/test-org/my-skill/1.0.0",
            headers=auth_headers,
        )

        assert resp.status_code == 403

    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    def test_delete_org_not_found(
        self,
        mock_find_org: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Deleting from a non-existent org should return 404."""
        mock_find_org.return_value = None

        resp = client.delete(
            "/v1/skills/no-org/my-skill/1.0.0",
            headers=auth_headers,
        )

        assert resp.status_code == 404

    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_routes.find_org_member")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    def test_delete_skill_not_found(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Deleting a non-existent skill should return 404."""
        org = _make_org(sample_user_id)
        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org, sample_user_id)
        mock_find_skill.return_value = None

        resp = client.delete(
            "/v1/skills/test-org/no-skill/1.0.0",
            headers=auth_headers,
        )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    @patch("decision_hub.api.registry_routes.delete_version")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_routes.find_org_member")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    def test_delete_version_not_found(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        mock_delete_version: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Deleting a non-existent version should return 404."""
        org = _make_org(sample_user_id)
        skill = _make_skill(org)
        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org, sample_user_id)
        mock_find_skill.return_value = skill
        mock_delete_version.return_value = False

        resp = client.delete(
            "/v1/skills/test-org/my-skill/9.9.9",
            headers=auth_headers,
        )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    @patch("decision_hub.api.registry_routes.delete_skill_zip")
    @patch("decision_hub.api.registry_routes.delete_version")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_routes.find_org_member")
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    def test_delete_allowed_for_admin(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        mock_delete_version: MagicMock,
        mock_delete_zip: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Admins (not just owners) should be able to delete."""
        org = _make_org(sample_user_id)
        skill = _make_skill(org)
        mock_find_org.return_value = org
        mock_find_member.return_value = OrgMember(
            org_id=org.id, user_id=sample_user_id, role="admin",
        )
        mock_find_skill.return_value = skill
        mock_delete_version.return_value = True

        resp = client.delete(
            "/v1/skills/test-org/my-skill/1.0.0",
            headers=auth_headers,
        )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /v1/skills
# ---------------------------------------------------------------------------

class TestListSkills:
    """GET /v1/skills -- list all published skills."""

    @patch("decision_hub.api.registry_routes.fetch_all_skills_for_index")
    def test_list_skills_empty(
        self,
        mock_fetch: MagicMock,
        client: TestClient,
    ) -> None:
        """Empty registry returns an empty list."""
        mock_fetch.return_value = []

        resp = client.get("/v1/skills")

        assert resp.status_code == 200
        assert resp.json() == []

    @patch("decision_hub.api.registry_routes.fetch_all_skills_for_index")
    def test_list_skills_returns_data(
        self,
        mock_fetch: MagicMock,
        client: TestClient,
    ) -> None:
        """Skills are returned with all expected fields."""
        from datetime import datetime, timezone

        mock_fetch.return_value = [
            {
                "org_slug": "acme",
                "skill_name": "doc-writer",
                "description": "Writes documentation",
                "latest_version": "1.2.0",
                "eval_status": "passed",
                "created_at": datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
                "published_by": "alice",
            },
        ]

        resp = client.get("/v1/skills")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        skill = data[0]
        assert skill["org_slug"] == "acme"
        assert skill["skill_name"] == "doc-writer"
        assert skill["description"] == "Writes documentation"
        assert skill["latest_version"] == "1.2.0"
        assert skill["updated_at"] == "2025-06-01 12:00:00"
        assert skill["safety_rating"] == "A"
        assert skill["author"] == "alice"

    @patch("decision_hub.api.registry_routes.fetch_all_skills_for_index")
    def test_list_skills_safety_rating(
        self,
        mock_fetch: MagicMock,
        client: TestClient,
    ) -> None:
        """Safety rating maps eval_status correctly."""
        mock_fetch.return_value = [
            {
                "org_slug": "org1",
                "skill_name": "safe-skill",
                "description": "",
                "latest_version": "1.0.0",
                "eval_status": "passed",
                "created_at": None,
                "published_by": "alice",
            },
            {
                "org_slug": "org2",
                "skill_name": "pending-skill",
                "description": "",
                "latest_version": "0.1.0",
                "eval_status": "pending",
                "created_at": None,
                "published_by": "bob",
            },
            {
                "org_slug": "org3",
                "skill_name": "failed-skill",
                "description": "",
                "latest_version": "2.0.0",
                "eval_status": "failed",
                "created_at": None,
                "published_by": "",
            },
        ]

        resp = client.get("/v1/skills")

        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["safety_rating"] == "A"
        assert data[1]["safety_rating"] == "C"
        assert data[2]["safety_rating"] == "F"

    @patch("decision_hub.api.registry_routes.fetch_all_skills_for_index")
    def test_list_skills_does_not_require_auth(
        self,
        mock_fetch: MagicMock,
        client: TestClient,
    ) -> None:
        """List endpoint is public — no auth required."""
        mock_fetch.return_value = []

        resp = client.get("/v1/skills")

        assert resp.status_code == 200
