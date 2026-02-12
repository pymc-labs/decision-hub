"""Tests for decision_hub.api.registry_routes -- publish, resolve, and delete endpoints."""

import io
import json
import zipfile
from datetime import UTC
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

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


def _make_version(
    skill: Skill,
    semver: str = "1.0.0",
    published_by: str = "testuser",
    eval_status: str = "A",
) -> Version:
    return Version(
        id=uuid4(),
        skill_id=skill.id,
        semver=semver,
        s3_key=f"skills/test-org/{skill.name}/{semver}.zip",
        checksum="abc123def456",
        runtime_config=None,
        eval_status=eval_status,
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
    metadata = json.dumps(
        {
            "org_slug": org_slug,
            "skill_name": skill_name,
            "version": version,
        }
    )
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

    def test_publish_returns_503_without_llm(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_settings: MagicMock,
    ) -> None:
        """Publishing without google_api_key returns 503."""
        test_settings.google_api_key = ""

        resp = _publish_request(client, auth_headers)

        assert resp.status_code == 503
        assert "LLM judge" in resp.json()["detail"]

    @patch("decision_hub.api.registry_routes.classify_skill_category", return_value="Other & Utilities")
    @patch("decision_hub.api.registry_service._build_analyze_prompt_fn", return_value=None)
    @patch("decision_hub.api.registry_service._build_analyze_fn", return_value=None)
    @patch("decision_hub.api.registry_routes.insert_audit_log")
    @patch("decision_hub.api.registry_routes.update_skill_category")
    @patch("decision_hub.api.registry_routes.update_skill_description")
    @patch("decision_hub.api.registry_routes.insert_version")
    @patch("decision_hub.api.registry_routes.find_version")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_routes.upload_skill_zip")
    @patch("decision_hub.api.registry_routes.compute_checksum")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
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
        mock_update_cat: MagicMock,
        mock_insert_audit: MagicMock,
        _mock_analyze_fn: MagicMock,
        _mock_prompt_fn: MagicMock,
        _mock_classify: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
        test_settings: MagicMock,
    ) -> None:
        """Full publish flow: org exists, user is member, skill exists, Gauntlet passes."""
        test_settings.google_api_key = "test-key"
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
        assert data["eval_status"] in ("A", "B")
        # Existing skill gets its description updated
        mock_update_desc.assert_called_once()
        # Audit log inserted for successful publish
        mock_insert_audit.assert_called_once()

    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_publish_org_not_found(
        self,
        mock_find_org: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        test_settings: MagicMock,
    ) -> None:
        """Publishing to a non-existent org should return 404."""
        test_settings.google_api_key = "test-key"
        mock_find_org.return_value = None

        resp = _publish_request(client, auth_headers, org_slug="no-such-org")

        assert resp.status_code == 404
        assert "Organisation not found" in resp.json()["detail"]

    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_publish_not_member(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
        test_settings: MagicMock,
    ) -> None:
        """Publishing when user is not an org member should return 403."""
        test_settings.google_api_key = "test-key"
        org = _make_org(sample_user_id)
        mock_find_org.return_value = org
        mock_find_member.return_value = None

        resp = _publish_request(client, auth_headers)

        assert resp.status_code == 403
        assert "not a member" in resp.json()["detail"]

    def test_publish_no_auth(self, client: TestClient) -> None:
        """Publishing without auth should return 401."""
        metadata = json.dumps(
            {
                "org_slug": "test-org",
                "skill_name": "my-skill",
                "version": "1.0.0",
            }
        )
        resp = client.post(
            "/v1/publish",
            data={"metadata": metadata},
            files={"zip_file": ("skill.zip", _make_skill_zip(), "application/zip")},
        )

        assert resp.status_code == 401

    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_publish_rejects_oversized_upload(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
        test_settings: MagicMock,
    ) -> None:
        """Uploading a zip exceeding 50 MB should return 413."""
        test_settings.google_api_key = "test-key"
        org = _make_org(sample_user_id)
        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org, sample_user_id)

        # Create a payload just over the limit (50 MB + 2 bytes)
        oversized = b"\x00" * (50 * 1024 * 1024 + 2)

        resp = _publish_request(client, auth_headers, zip_bytes=oversized)

        assert resp.status_code == 413
        assert "maximum size" in resp.json()["detail"]

    @patch("decision_hub.api.registry_routes.classify_skill_category", return_value="Other & Utilities")
    @patch("decision_hub.api.registry_service._build_analyze_prompt_fn", return_value=None)
    @patch("decision_hub.api.registry_service._build_analyze_fn", return_value=None)
    @patch("decision_hub.api.registry_routes.insert_audit_log")
    @patch("decision_hub.api.registry_routes.insert_version")
    @patch("decision_hub.api.registry_routes.find_version")
    @patch("decision_hub.api.registry_routes.insert_skill")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_routes.upload_skill_zip")
    @patch("decision_hub.api.registry_routes.compute_checksum")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
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
        mock_insert_audit: MagicMock,
        _mock_analyze_fn: MagicMock,
        _mock_prompt_fn: MagicMock,
        _mock_classify: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
        test_settings: MagicMock,
    ) -> None:
        """When skill doesn't exist yet, it should be created via insert_skill."""
        test_settings.google_api_key = "test-key"
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
            client,
            auth_headers,
            skill_name="brand-new-skill",
        )

        assert resp.status_code == 201
        mock_insert_skill.assert_called_once_with(
            mock_find_org.call_args[0][0],  # the conn argument
            org.id,
            "brand-new-skill",
            "A test skill",  # description extracted from SKILL.md
            category="Other & Utilities",
            visibility="public",
        )
        assert resp.json()["skill_id"] == str(new_skill.id)

    @patch("decision_hub.api.registry_routes.classify_skill_category", return_value="Other & Utilities")
    @patch("decision_hub.api.registry_service._build_analyze_prompt_fn", return_value=None)
    @patch("decision_hub.api.registry_service._build_analyze_fn", return_value=None)
    @patch("decision_hub.api.registry_routes.update_skill_category")
    @patch("decision_hub.api.registry_routes.update_skill_description")
    @patch("decision_hub.api.registry_routes.find_version")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_routes.compute_checksum")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_publish_duplicate_version(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_checksum: MagicMock,
        mock_find_skill: MagicMock,
        mock_find_version: MagicMock,
        _mock_update_desc: MagicMock,
        _mock_update_cat: MagicMock,
        _mock_analyze_fn: MagicMock,
        _mock_prompt_fn: MagicMock,
        _mock_classify: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
        test_settings: MagicMock,
    ) -> None:
        """Publishing an already-existing version should return 409."""
        test_settings.google_api_key = "test-key"
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

    @patch("decision_hub.api.registry_service._build_analyze_prompt_fn", return_value=None)
    @patch("decision_hub.api.registry_service._build_analyze_fn", return_value=None)
    @patch("decision_hub.api.registry_service.insert_audit_log")
    @patch("decision_hub.api.registry_service.upload_skill_zip")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_publish_gauntlet_blocks_dangerous_skill(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_upload: MagicMock,
        mock_insert_audit: MagicMock,
        _mock_analyze_fn: MagicMock,
        _mock_prompt_fn: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
        test_settings: MagicMock,
    ) -> None:
        """Publish should return 422 when SKILL.md manifest is malformed.

        With fail-closed parsing, a malformed manifest is rejected before
        the gauntlet static checks run — no quarantine or audit log.
        """
        test_settings.google_api_key = "test-key"
        org = _make_org(sample_user_id)
        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org, sample_user_id)

        # Zip with missing required fields in SKILL.md (no name/description)
        zip_bytes = _make_skill_zip(skill_md="# Just a heading\nNo frontmatter\n")
        resp = _publish_request(client, auth_headers, zip_bytes=zip_bytes)

        assert resp.status_code == 422
        assert "malformed" in resp.json()["detail"].lower()

    @patch("decision_hub.api.registry_service._build_analyze_prompt_fn", return_value=None)
    @patch("decision_hub.api.registry_service._build_analyze_fn", return_value=None)
    @patch("decision_hub.api.registry_service.insert_audit_log")
    @patch("decision_hub.api.registry_service.upload_skill_zip")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_publish_gauntlet_blocks_suspicious_code(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_upload: MagicMock,
        mock_insert_audit: MagicMock,
        _mock_analyze_fn: MagicMock,
        _mock_prompt_fn: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
        test_settings: MagicMock,
    ) -> None:
        """Publish should return 422 when safety scan detects suspicious patterns."""
        test_settings.google_api_key = "test-key"
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
        # Rejected zip uploaded to quarantine
        mock_upload.assert_called_once()
        assert mock_upload.call_args[0][2].startswith("rejected/")

    def test_publish_malformed_json(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_settings: MagicMock,
    ) -> None:
        """Malformed JSON metadata returns 422, not 500."""
        test_settings.google_api_key = "test-key"
        resp = client.post(
            "/v1/publish",
            data={"metadata": "not-valid-json"},
            files={"zip_file": ("skill.zip", _make_skill_zip(), "application/zip")},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert "Invalid JSON" in resp.json()["detail"]

    def test_publish_missing_metadata_keys(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_settings: MagicMock,
    ) -> None:
        """Missing required keys in metadata returns 422."""
        test_settings.google_api_key = "test-key"
        resp = client.post(
            "/v1/publish",
            data={"metadata": json.dumps({"org_slug": "test-org"})},
            files={"zip_file": ("skill.zip", _make_skill_zip(), "application/zip")},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert "Missing required metadata keys" in resp.json()["detail"]

    def test_publish_invalid_semver(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_settings: MagicMock,
    ) -> None:
        """Invalid semver in metadata returns 422."""
        test_settings.google_api_key = "test-key"
        resp = _publish_request(client, auth_headers, version="not.a.version")
        assert resp.status_code == 422
        assert "Invalid semver" in resp.json()["detail"]

    def test_publish_invalid_skill_name(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_settings: MagicMock,
    ) -> None:
        """Invalid skill name in metadata returns 422."""
        test_settings.google_api_key = "test-key"
        resp = _publish_request(client, auth_headers, skill_name="INVALID NAME!")
        assert resp.status_code == 422
        assert "Invalid skill name" in resp.json()["detail"]

    @patch("decision_hub.api.registry_routes.classify_skill_category", return_value="Other & Utilities")
    @patch("decision_hub.api.registry_service._build_analyze_prompt_fn", return_value=None)
    @patch("decision_hub.api.registry_service._build_analyze_fn", return_value=None)
    @patch("decision_hub.api.registry_routes.insert_audit_log")
    @patch("decision_hub.api.registry_routes.insert_version")
    @patch("decision_hub.api.registry_routes.find_version")
    @patch("decision_hub.api.registry_routes.update_skill_category")
    @patch("decision_hub.api.registry_routes.update_skill_description")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_routes.upload_skill_zip")
    @patch("decision_hub.api.registry_routes.compute_checksum")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_publish_race_condition_returns_409(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_checksum: MagicMock,
        mock_upload: MagicMock,
        mock_find_skill: MagicMock,
        _mock_update_desc: MagicMock,
        _mock_update_cat: MagicMock,
        mock_find_version: MagicMock,
        mock_insert_version: MagicMock,
        mock_insert_audit: MagicMock,
        _mock_analyze_fn: MagicMock,
        _mock_prompt_fn: MagicMock,
        _mock_classify: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
        test_settings: MagicMock,
    ) -> None:
        """Concurrent publish race condition returns 409 instead of 500."""
        from sqlalchemy.exc import IntegrityError

        test_settings.google_api_key = "test-key"
        org = _make_org(sample_user_id)
        skill = _make_skill(org)

        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org, sample_user_id)
        mock_checksum.return_value = "abc123def456"
        mock_find_skill.return_value = skill
        mock_find_version.return_value = None  # check passes
        mock_insert_version.side_effect = IntegrityError("duplicate", params=None, orig=Exception())

        resp = _publish_request(client, auth_headers)

        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /v1/resolve/{org_slug}/{skill_name}
# ---------------------------------------------------------------------------


class TestResolveSkill:
    """GET /v1/resolve/{org_slug}/{skill_name} -- resolve a skill version."""

    @patch("decision_hub.api.registry_routes.increment_skill_downloads")
    @patch("decision_hub.api.registry_routes.generate_presigned_url")
    @patch("decision_hub.api.registry_routes.resolve_version")
    def test_resolve_success(
        self,
        mock_resolve: MagicMock,
        mock_presign: MagicMock,
        mock_increment: MagicMock,
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
        mock_increment.assert_called_once()
        assert mock_increment.call_args[0][1] == version.skill_id

    @patch("decision_hub.api.registry_routes.increment_skill_downloads")
    @patch("decision_hub.api.registry_routes.resolve_version")
    def test_resolve_not_found(
        self,
        mock_resolve: MagicMock,
        mock_increment: MagicMock,
        client: TestClient,
    ) -> None:
        """Resolving a non-existent version should return 404."""
        mock_resolve.return_value = None

        resp = client.get("/v1/resolve/test-org/my-skill?spec=latest")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]
        mock_increment.assert_not_called()

    @patch("decision_hub.api.registry_routes.increment_skill_downloads")
    @patch("decision_hub.api.registry_routes.generate_presigned_url")
    @patch("decision_hub.api.registry_routes.resolve_version")
    def test_resolve_with_specific_version(
        self,
        mock_resolve: MagicMock,
        mock_presign: MagicMock,
        mock_increment: MagicMock,
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

    @patch("decision_hub.api.registry_routes.increment_skill_downloads")
    @patch("decision_hub.api.registry_routes.generate_presigned_url")
    @patch("decision_hub.api.registry_routes.resolve_version")
    def test_resolve_does_not_require_auth(
        self,
        mock_resolve: MagicMock,
        mock_presign: MagicMock,
        mock_increment: MagicMock,
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

    @patch("decision_hub.api.registry_routes.increment_skill_downloads")
    @patch("decision_hub.api.registry_routes.generate_presigned_url")
    @patch("decision_hub.api.registry_routes.resolve_version")
    def test_resolve_with_allow_risky(
        self,
        mock_resolve: MagicMock,
        mock_presign: MagicMock,
        mock_increment: MagicMock,
        client: TestClient,
    ) -> None:
        """Resolve with allow_risky=true passes the flag through."""
        org = _make_org()
        skill = _make_skill(org)
        version = _make_version(skill, eval_status="C")

        mock_resolve.return_value = version
        mock_presign.return_value = "https://s3.example.com/risky"

        resp = client.get("/v1/resolve/test-org/my-skill?spec=latest&allow_risky=true")

        assert resp.status_code == 200
        # Verify allow_risky was passed to resolve_version
        mock_resolve.assert_called_once()
        call_kwargs = mock_resolve.call_args
        assert call_kwargs.kwargs.get("allow_risky") is True


# ---------------------------------------------------------------------------
# GET /v1/skills/{org_slug}/{skill_name}/audit-log
# ---------------------------------------------------------------------------


class TestGetAuditLog:
    """GET /v1/skills/{org}/{skill}/audit-log -- evaluation history."""

    @patch("decision_hub.api.registry_routes.find_audit_logs")
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    def test_audit_log_empty(
        self,
        mock_find_skill: MagicMock,
        mock_find: MagicMock,
        client: TestClient,
    ) -> None:
        """Returns empty list when no audit logs exist."""
        mock_find_skill.return_value = _make_skill(_make_org())
        mock_find.return_value = []

        resp = client.get("/v1/skills/test-org/my-skill/audit-log")

        assert resp.status_code == 200
        assert resp.json() == []

    @patch("decision_hub.api.registry_routes.find_audit_logs")
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    def test_audit_log_returns_entries(
        self,
        mock_find_skill: MagicMock,
        mock_find: MagicMock,
        client: TestClient,
    ) -> None:
        """Returns audit log entries with all fields."""
        from datetime import datetime

        from decision_hub.models import AuditLogEntry

        mock_find_skill.return_value = _make_skill(_make_org())
        entry = AuditLogEntry(
            id=uuid4(),
            org_slug="test-org",
            skill_name="my-skill",
            semver="1.0.0",
            grade="A",
            version_id=uuid4(),
            check_results=[{"check_name": "manifest_schema", "severity": "pass", "message": "ok"}],
            llm_reasoning=None,
            publisher="testuser",
            quarantine_s3_key=None,
            created_at=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
        )
        mock_find.return_value = [entry]

        resp = client.get("/v1/skills/test-org/my-skill/audit-log")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["grade"] == "A"
        assert data[0]["publisher"] == "testuser"

    @patch("decision_hub.api.registry_routes.find_audit_logs")
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    def test_audit_log_does_not_require_auth_for_public_skills(
        self,
        mock_find_skill: MagicMock,
        mock_find: MagicMock,
        client: TestClient,
    ) -> None:
        """Audit log endpoint works without auth for public skills."""
        mock_find_skill.return_value = _make_skill(_make_org())
        mock_find.return_value = []

        resp = client.get("/v1/skills/test-org/my-skill/audit-log")

        assert resp.status_code == 200

    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    def test_audit_log_returns_404_for_invisible_skill(
        self,
        mock_find_skill: MagicMock,
        client: TestClient,
    ) -> None:
        """Audit log returns 404 when skill is not visible (private + unauthenticated)."""
        mock_find_skill.return_value = None

        resp = client.get("/v1/skills/test-org/private-skill/audit-log")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /v1/skills/{org_slug}/{skill_name}/eval-report -- visibility checks
# ---------------------------------------------------------------------------


class TestEvalReportVisibility:
    """Eval report endpoints should respect visibility filtering."""

    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    def test_eval_report_returns_404_for_invisible_skill(
        self,
        mock_find_skill: MagicMock,
        client: TestClient,
    ) -> None:
        """Eval report returns 404 when skill is not visible."""
        mock_find_skill.return_value = None

        resp = client.get("/v1/skills/test-org/private-skill/eval-report?semver=1.0.0")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    def test_eval_report_by_version_path_returns_404_for_invisible_skill(
        self,
        mock_find_skill: MagicMock,
        client: TestClient,
    ) -> None:
        """Eval report (path-based) returns 404 when skill is not visible."""
        mock_find_skill.return_value = None

        resp = client.get("/v1/skills/test-org/private-skill/versions/1.0.0/eval-report")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    @patch("decision_hub.api.registry_routes.find_eval_report_by_skill")
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    def test_eval_report_accessible_for_visible_skill(
        self,
        mock_find_skill: MagicMock,
        mock_find_report: MagicMock,
        client: TestClient,
    ) -> None:
        """Eval report is accessible when skill is visible (public)."""
        mock_find_skill.return_value = _make_skill(_make_org())
        mock_find_report.return_value = None

        resp = client.get("/v1/skills/test-org/my-skill/eval-report?semver=1.0.0")

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# DELETE /v1/skills/{org_slug}/{skill_name}/{version}
# ---------------------------------------------------------------------------


class TestDeleteSkillVersion:
    """DELETE /v1/skills/{org_slug}/{skill_name}/{version} -- delete a published version."""

    @patch("decision_hub.api.registry_routes.delete_skill_zip")
    @patch("decision_hub.api.registry_routes.delete_version")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
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

    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
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
            org_id=org.id,
            user_id=sample_user_id,
            role="member",
        )

        resp = client.delete(
            "/v1/skills/test-org/my-skill/1.0.0",
            headers=auth_headers,
        )

        assert resp.status_code == 403
        assert "owners and admins" in resp.json()["detail"]

    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
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

    @patch("decision_hub.api.registry_service.find_org_by_slug")
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
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
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
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
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
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
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
            org_id=org.id,
            user_id=sample_user_id,
            role="admin",
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

    @patch("decision_hub.api.registry_routes.count_all_skills", return_value=0)
    @patch("decision_hub.api.registry_routes.fetch_all_skills_for_index")
    def test_list_skills_empty(
        self,
        mock_fetch: MagicMock,
        mock_count: MagicMock,
        client: TestClient,
    ) -> None:
        """Empty registry returns an empty items list."""
        mock_fetch.return_value = []

        resp = client.get("/v1/skills")

        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert data["total_pages"] == 1

    @patch("decision_hub.api.registry_routes.count_all_skills", return_value=1)
    @patch("decision_hub.api.registry_routes.fetch_all_skills_for_index")
    def test_list_skills_returns_data(
        self,
        mock_fetch: MagicMock,
        mock_count: MagicMock,
        client: TestClient,
    ) -> None:
        """Skills are returned with all expected fields."""
        from datetime import datetime

        mock_fetch.return_value = [
            {
                "org_slug": "acme",
                "skill_name": "doc-writer",
                "description": "Writes documentation",
                "download_count": 42,
                "latest_version": "1.2.0",
                "eval_status": "A",
                "created_at": datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
                "published_by": "alice",
            },
        ]

        resp = client.get("/v1/skills")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        skill = data["items"][0]
        assert skill["org_slug"] == "acme"
        assert skill["skill_name"] == "doc-writer"
        assert skill["description"] == "Writes documentation"
        assert skill["latest_version"] == "1.2.0"
        assert skill["updated_at"] == "2025-06-01 12:00:00"
        assert skill["safety_rating"] == "A"
        assert skill["author"] == "alice"
        assert skill["download_count"] == 42

    @patch("decision_hub.api.registry_routes.count_all_skills", return_value=4)
    @patch("decision_hub.api.registry_routes.fetch_all_skills_for_index")
    def test_list_skills_safety_rating(
        self,
        mock_fetch: MagicMock,
        mock_count: MagicMock,
        client: TestClient,
    ) -> None:
        """Safety rating maps eval_status correctly for both new and legacy values."""
        mock_fetch.return_value = [
            {
                "org_slug": "org1",
                "skill_name": "safe-skill",
                "description": "",
                "download_count": 0,
                "latest_version": "1.0.0",
                "eval_status": "A",
                "created_at": None,
                "published_by": "alice",
            },
            {
                "org_slug": "org2",
                "skill_name": "verified-skill",
                "description": "",
                "download_count": 0,
                "latest_version": "0.1.0",
                "eval_status": "B",
                "created_at": None,
                "published_by": "bob",
            },
            {
                "org_slug": "org3",
                "skill_name": "risky-skill",
                "description": "",
                "download_count": 0,
                "latest_version": "2.0.0",
                "eval_status": "C",
                "created_at": None,
                "published_by": "",
            },
            {
                "org_slug": "org4",
                "skill_name": "legacy-skill",
                "description": "",
                "download_count": 0,
                "latest_version": "1.0.0",
                "eval_status": "passed",
                "created_at": None,
                "published_by": "",
            },
        ]

        resp = client.get("/v1/skills")

        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items[0]["safety_rating"] == "A"
        assert items[1]["safety_rating"] == "B"
        assert items[2]["safety_rating"] == "C"
        assert items[3]["safety_rating"] == "A"  # legacy "passed" -> A

    @patch("decision_hub.api.registry_routes.count_all_skills", return_value=0)
    @patch("decision_hub.api.registry_routes.fetch_all_skills_for_index")
    def test_list_skills_does_not_require_auth(
        self,
        mock_fetch: MagicMock,
        mock_count: MagicMock,
        client: TestClient,
    ) -> None:
        """List endpoint is public — no auth required."""
        mock_fetch.return_value = []

        resp = client.get("/v1/skills")

        assert resp.status_code == 200

    @patch("decision_hub.api.registry_routes.count_all_skills", return_value=25)
    @patch("decision_hub.api.registry_routes.fetch_all_skills_for_index")
    def test_list_skills_pagination_params(
        self,
        mock_fetch: MagicMock,
        mock_count: MagicMock,
        client: TestClient,
    ) -> None:
        """Page and page_size query params are forwarded correctly."""
        mock_fetch.return_value = []

        resp = client.get("/v1/skills?page=2&page_size=10")

        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["page_size"] == 10
        assert data["total"] == 25
        assert data["total_pages"] == 3
        mock_fetch.assert_called_once()
        call_kwargs = mock_fetch.call_args
        assert call_kwargs.kwargs["limit"] == 10
        assert call_kwargs.kwargs["offset"] == 10

    @patch("decision_hub.api.registry_routes.count_all_skills", return_value=0)
    @patch("decision_hub.api.registry_routes.fetch_all_skills_for_index")
    def test_list_skills_page_size_limit(
        self,
        mock_fetch: MagicMock,
        mock_count: MagicMock,
        client: TestClient,
    ) -> None:
        """page_size > 100 is rejected by validation."""
        mock_fetch.return_value = []

        resp = client.get("/v1/skills?page_size=200")

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/skills/{org_slug}/{skill_name}/latest-version
# ---------------------------------------------------------------------------


class TestGetLatestVersion:
    """GET /v1/skills/{org}/{skill}/latest-version -- returns the latest published version."""

    @patch("decision_hub.api.registry_routes.resolve_latest_version")
    def test_latest_version_success(
        self,
        mock_resolve: MagicMock,
        client: TestClient,
    ) -> None:
        """Returns the latest version string."""
        org = _make_org()
        skill = _make_skill(org)
        version = _make_version(skill, semver="2.3.1")
        mock_resolve.return_value = version

        resp = client.get("/v1/skills/test-org/my-skill/latest-version")

        assert resp.status_code == 200
        assert resp.json()["version"] == "2.3.1"
        assert resp.json()["checksum"] == "abc123def456"

    @patch("decision_hub.api.registry_routes.resolve_latest_version")
    def test_latest_version_not_found(
        self,
        mock_resolve: MagicMock,
        client: TestClient,
    ) -> None:
        """Returns 404 when no versions exist for the skill."""
        mock_resolve.return_value = None

        resp = client.get("/v1/skills/test-org/no-skill/latest-version")

        assert resp.status_code == 404
        assert "No versions found" in resp.json()["detail"]

    @patch("decision_hub.api.registry_routes.resolve_latest_version")
    def test_latest_version_does_not_require_auth(
        self,
        mock_resolve: MagicMock,
        client: TestClient,
    ) -> None:
        """Latest-version endpoint is public — no auth required."""
        org = _make_org()
        skill = _make_skill(org)
        mock_resolve.return_value = _make_version(skill)

        resp = client.get("/v1/skills/test-org/my-skill/latest-version")

        assert resp.status_code == 200

    @patch("decision_hub.api.registry_routes.list_user_org_ids")
    @patch("decision_hub.api.registry_routes.resolve_latest_version")
    def test_latest_version_passes_user_org_ids_when_authenticated(
        self,
        mock_resolve: MagicMock,
        mock_list_orgs: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Authenticated requests pass user_org_ids for visibility filtering."""
        org = _make_org()
        skill = _make_skill(org)
        mock_list_orgs.return_value = [org.id]
        mock_resolve.return_value = _make_version(skill)

        resp = client.get("/v1/skills/test-org/my-skill/latest-version", headers=auth_headers)

        assert resp.status_code == 200
        mock_list_orgs.assert_called_once()
        mock_resolve.assert_called_once()
        assert mock_resolve.call_args.kwargs["user_org_ids"] == [org.id]

    @patch("decision_hub.api.registry_routes.resolve_latest_version")
    def test_latest_version_unauthenticated_passes_none_org_ids(
        self,
        mock_resolve: MagicMock,
        client: TestClient,
    ) -> None:
        """Unauthenticated requests pass user_org_ids=None (public only)."""
        mock_resolve.return_value = None

        resp = client.get("/v1/skills/test-org/private-skill/latest-version")

        assert resp.status_code == 404
        mock_resolve.assert_called_once()
        assert mock_resolve.call_args.kwargs["user_org_ids"] is None


# ---------------------------------------------------------------------------
# GET /v1/skills/{org_slug}/{skill_name}/download -- visibility checks
# ---------------------------------------------------------------------------


class TestDownloadSkillVisibility:
    """GET /v1/skills/{org}/{skill}/download -- visibility filtering."""

    @patch("decision_hub.api.registry_routes.increment_skill_downloads")
    @patch("decision_hub.api.registry_routes.download_zip_from_s3")
    @patch("decision_hub.api.registry_routes.list_user_org_ids")
    @patch("decision_hub.api.registry_routes.resolve_version")
    def test_download_passes_user_org_ids_when_authenticated(
        self,
        mock_resolve: MagicMock,
        mock_list_orgs: MagicMock,
        mock_download: MagicMock,
        mock_increment: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Authenticated download passes user_org_ids for visibility filtering."""
        org = _make_org()
        skill = _make_skill(org)
        version = _make_version(skill)
        mock_list_orgs.return_value = [org.id]
        mock_resolve.return_value = version
        mock_download.return_value = b"zipdata"

        resp = client.get("/v1/skills/test-org/my-skill/download", headers=auth_headers)

        assert resp.status_code == 200
        mock_resolve.assert_called_once()
        assert mock_resolve.call_args.kwargs["user_org_ids"] == [org.id]

    @patch("decision_hub.api.registry_routes.resolve_version")
    def test_download_unauthenticated_passes_none_org_ids(
        self,
        mock_resolve: MagicMock,
        client: TestClient,
    ) -> None:
        """Unauthenticated download passes user_org_ids=None (public only)."""
        mock_resolve.return_value = None

        resp = client.get("/v1/skills/test-org/private-skill/download")

        assert resp.status_code == 404
        mock_resolve.assert_called_once()
        assert mock_resolve.call_args.kwargs["user_org_ids"] is None


# ---------------------------------------------------------------------------
# POST /v1/publish -- visibility preservation on re-publish
# ---------------------------------------------------------------------------


class TestPublishVisibilityPreservation:
    """POST /v1/publish -- visibility is preserved when not explicitly provided."""

    @patch("decision_hub.api.registry_service._build_analyze_prompt_fn", return_value=None)
    @patch("decision_hub.api.registry_service._build_analyze_fn", return_value=None)
    @patch("decision_hub.api.registry_routes.insert_audit_log")
    @patch("decision_hub.api.registry_routes.update_skill_visibility")
    @patch("decision_hub.api.registry_routes.update_skill_description")
    @patch("decision_hub.api.registry_routes.insert_version")
    @patch("decision_hub.api.registry_routes.find_version")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_routes.upload_skill_zip")
    @patch("decision_hub.api.registry_routes.compute_checksum")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_republish_without_visibility_preserves_existing(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_checksum: MagicMock,
        mock_upload: MagicMock,
        mock_find_skill: MagicMock,
        mock_find_version: MagicMock,
        mock_insert_version: MagicMock,
        mock_update_desc: MagicMock,
        mock_update_vis: MagicMock,
        mock_insert_audit: MagicMock,
        _mock_analyze_fn: MagicMock,
        _mock_prompt_fn: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
        test_settings: MagicMock,
    ) -> None:
        """Re-publishing without --private should NOT reset visibility to public."""
        test_settings.google_api_key = "test-key"
        org = _make_org(sample_user_id)
        skill = _make_skill(org)
        skill = Skill(
            id=skill.id, org_id=skill.org_id, name=skill.name, description=skill.description, visibility="org"
        )
        version = _make_version(skill, semver="2.0.0")

        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org, sample_user_id)
        mock_checksum.return_value = "abc123def456"
        mock_find_skill.return_value = skill
        mock_find_version.return_value = None
        mock_insert_version.return_value = version

        # Publish without visibility in metadata (no --private flag)
        metadata = json.dumps({"org_slug": "test-org", "skill_name": "my-skill", "version": "2.0.0"})
        resp = client.post(
            "/v1/publish",
            data={"metadata": metadata},
            files={"zip_file": ("skill.zip", _make_skill_zip(), "application/zip")},
            headers=auth_headers,
        )

        assert resp.status_code == 201
        # update_skill_visibility should NOT have been called
        mock_update_vis.assert_not_called()

    @patch("decision_hub.api.registry_service._build_analyze_prompt_fn", return_value=None)
    @patch("decision_hub.api.registry_service._build_analyze_fn", return_value=None)
    @patch("decision_hub.api.registry_routes.insert_audit_log")
    @patch("decision_hub.api.registry_routes.update_skill_visibility")
    @patch("decision_hub.api.registry_routes.update_skill_description")
    @patch("decision_hub.api.registry_routes.insert_version")
    @patch("decision_hub.api.registry_routes.find_version")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_routes.upload_skill_zip")
    @patch("decision_hub.api.registry_routes.compute_checksum")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_republish_with_explicit_visibility_updates_it(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_checksum: MagicMock,
        mock_upload: MagicMock,
        mock_find_skill: MagicMock,
        mock_find_version: MagicMock,
        mock_insert_version: MagicMock,
        mock_update_desc: MagicMock,
        mock_update_vis: MagicMock,
        mock_insert_audit: MagicMock,
        _mock_analyze_fn: MagicMock,
        _mock_prompt_fn: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
        test_settings: MagicMock,
    ) -> None:
        """Re-publishing with explicit visibility should update it."""
        test_settings.google_api_key = "test-key"
        org = _make_org(sample_user_id)
        skill = _make_skill(org)
        version = _make_version(skill, semver="2.0.0")

        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org, sample_user_id)
        mock_checksum.return_value = "abc123def456"
        mock_find_skill.return_value = skill
        mock_find_version.return_value = None
        mock_insert_version.return_value = version

        # Publish WITH explicit visibility
        metadata = json.dumps(
            {
                "org_slug": "test-org",
                "skill_name": "my-skill",
                "version": "2.0.0",
                "visibility": "org",
            }
        )
        resp = client.post(
            "/v1/publish",
            data={"metadata": metadata},
            files={"zip_file": ("skill.zip", _make_skill_zip(), "application/zip")},
            headers=auth_headers,
        )

        assert resp.status_code == 201
        mock_update_vis.assert_called_once_with(mock_find_org.call_args[0][0], skill.id, "org")


# ---------------------------------------------------------------------------
# DELETE /v1/skills/{org_slug}/{skill_name} (all versions)
# ---------------------------------------------------------------------------


class TestDeleteAllVersions:
    """DELETE /v1/skills/{org}/{skill} -- delete all versions and the skill record."""

    @patch("decision_hub.api.registry_routes.delete_skill_zip")
    @patch("decision_hub.api.registry_routes.delete_skill_record")
    @patch("decision_hub.api.registry_routes.delete_all_versions")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_delete_all_success(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        mock_delete_all: MagicMock,
        mock_delete_skill: MagicMock,
        mock_delete_zip: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Owner can delete all versions successfully."""
        org = _make_org(sample_user_id)
        skill = _make_skill(org)

        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org, sample_user_id)
        mock_find_skill.return_value = skill
        mock_delete_all.return_value = [
            "skills/test-org/my-skill/1.0.0.zip",
            "skills/test-org/my-skill/1.1.0.zip",
        ]

        resp = client.delete(
            "/v1/skills/test-org/my-skill",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["org_slug"] == "test-org"
        assert data["skill_name"] == "my-skill"
        assert data["versions_deleted"] == 2
        assert mock_delete_zip.call_count == 2
        mock_delete_skill.assert_called_once()

    def test_delete_all_no_auth(self, client: TestClient) -> None:
        """Deleting without auth should return 401."""
        resp = client.delete("/v1/skills/test-org/my-skill")
        assert resp.status_code == 401

    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_delete_all_forbidden_for_member(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Regular members should get 403."""
        org = _make_org(sample_user_id)
        mock_find_org.return_value = org
        mock_find_member.return_value = OrgMember(
            org_id=org.id,
            user_id=sample_user_id,
            role="member",
        )

        resp = client.delete(
            "/v1/skills/test-org/my-skill",
            headers=auth_headers,
        )

        assert resp.status_code == 403

    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_delete_all_org_not_found(
        self,
        mock_find_org: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Deleting from a non-existent org should return 404."""
        mock_find_org.return_value = None

        resp = client.delete(
            "/v1/skills/no-org/my-skill",
            headers=auth_headers,
        )

        assert resp.status_code == 404

    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_delete_all_skill_not_found(
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
            "/v1/skills/test-org/no-skill",
            headers=auth_headers,
        )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    @patch("decision_hub.api.registry_routes.delete_skill_zip")
    @patch("decision_hub.api.registry_routes.delete_skill_record")
    @patch("decision_hub.api.registry_routes.delete_all_versions")
    @patch("decision_hub.api.registry_routes.find_skill")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_delete_all_allowed_for_admin(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_find_skill: MagicMock,
        mock_delete_all: MagicMock,
        mock_delete_skill: MagicMock,
        mock_delete_zip: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Admins should be able to delete all versions."""
        org = _make_org(sample_user_id)
        skill = _make_skill(org)
        mock_find_org.return_value = org
        mock_find_member.return_value = OrgMember(
            org_id=org.id,
            user_id=sample_user_id,
            role="admin",
        )
        mock_find_skill.return_value = skill
        mock_delete_all.return_value = ["key1.zip"]

        resp = client.delete(
            "/v1/skills/test-org/my-skill",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["versions_deleted"] == 1
