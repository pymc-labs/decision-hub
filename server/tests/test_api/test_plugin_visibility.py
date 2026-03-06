"""Tests for plugin visibility: publish propagation and read/search/resolve enforcement."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from decision_hub.models import Organization, OrgMember, Plugin, PluginVersion
from dhub_core.plugin_manifest import PluginManifest

# ---------------------------------------------------------------------------
# Shared test data helpers
# ---------------------------------------------------------------------------

SAMPLE_USER_ID = UUID("12345678-1234-5678-1234-567812345678")
SAMPLE_ORG_ID = uuid4()


def _make_org(owner_id: UUID = SAMPLE_USER_ID, slug: str = "test-org") -> Organization:
    return Organization(id=SAMPLE_ORG_ID, slug=slug, owner_id=owner_id)


def _make_member(org: Organization, user_id: UUID = SAMPLE_USER_ID) -> OrgMember:
    return OrgMember(org_id=org.id, user_id=user_id, role="owner")


def _make_plugin(
    org: Organization,
    name: str = "my-plugin",
    description: str = "A test plugin",
    visibility: str = "public",
) -> Plugin:
    return Plugin(
        id=uuid4(),
        org_id=org.id,
        name=name,
        description=description,
        visibility=visibility,
    )


def _make_plugin_version(
    plugin: Plugin,
    semver: str = "1.0.0",
) -> PluginVersion:
    return PluginVersion(
        id=uuid4(),
        plugin_id=plugin.id,
        semver=semver,
        s3_key=f"plugins/test-org/{plugin.name}/{semver}.zip",
        checksum="abc123",
        plugin_manifest=None,
        runtime_config=None,
        eval_status="A",
        published_by="testuser",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# Task 3: Publish propagates visibility
# ---------------------------------------------------------------------------


class TestPublishPluginVisibility:
    """POST /v1/plugins/publish -- visibility propagation."""

    @patch("decision_hub.infra.embeddings.generate_and_store_plugin_embedding")
    @patch("decision_hub.domain.plugin_publish_pipeline.upload_skill_zip")
    @patch("decision_hub.domain.plugin_publish_pipeline.classify_skill_category", return_value="devops")
    @patch("decision_hub.domain.plugin_publish_pipeline.run_plugin_static_checks")
    @patch("decision_hub.domain.plugin_publish_pipeline.extract_plugin_for_evaluation", return_value=([], []))
    @patch("decision_hub.domain.plugin_publish_pipeline.extract_plugin_to_dir")
    @patch("decision_hub.domain.plugin_publish_pipeline.parse_plugin_manifest")
    @patch("decision_hub.domain.plugin_publish_pipeline.insert_audit_log")
    @patch("decision_hub.domain.plugin_publish_pipeline.insert_plugin_version")
    @patch("decision_hub.domain.plugin_publish_pipeline.find_plugin_version", return_value=None)
    @patch("decision_hub.domain.plugin_publish_pipeline.insert_plugin")
    @patch("decision_hub.domain.plugin_publish_pipeline.find_plugin", return_value=None)
    @patch("decision_hub.domain.plugin_publish_pipeline.deprecate_skills_by_repo_url", return_value=0)
    @patch("decision_hub.api.plugin_routes.compute_checksum", return_value="abc123")
    @patch("decision_hub.api.registry_service.find_org_member")
    @patch("decision_hub.api.registry_service.find_org_by_slug")
    def test_publish_with_org_visibility(
        self,
        mock_find_org: MagicMock,
        mock_find_member: MagicMock,
        mock_checksum: MagicMock,
        mock_deprecate: MagicMock,
        mock_find_plugin: MagicMock,
        mock_insert_plugin: MagicMock,
        mock_find_version: MagicMock,
        mock_insert_version: MagicMock,
        mock_insert_audit: MagicMock,
        mock_parse_manifest: MagicMock,
        mock_extract_to_dir: MagicMock,
        mock_extract_for_eval: MagicMock,
        mock_gauntlet: MagicMock,
        mock_classify: MagicMock,
        mock_upload: MagicMock,
        mock_embedding: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        test_settings: MagicMock,
    ) -> None:
        """Publishing with visibility=org stores org visibility."""
        org = _make_org()
        plugin = _make_plugin(org, visibility="org")
        version = _make_plugin_version(plugin)

        mock_find_org.return_value = org
        mock_find_member.return_value = _make_member(org)
        test_settings.google_api_key = "test-key"

        mock_parse_manifest.return_value = PluginManifest(
            name="my-plugin",
            description="A test plugin",
            version="1.0.0",
            author_name="Test",
            author_email=None,
            homepage=None,
            repository=None,
            license=None,
            keywords=(),
            platforms=("claude",),
            skills=(),
            hooks=(),
            agents=(),
            commands=(),
        )

        # Mock gauntlet report
        report = MagicMock()
        report.passed = True
        report.grade = "A"
        report.gauntlet_summary = "All checks passed"
        report.results = []
        mock_gauntlet.return_value = report

        mock_insert_plugin.return_value = plugin
        mock_insert_version.return_value = version

        import io
        import json
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                ".claude-plugin/plugin.json",
                json.dumps({"name": "my-plugin", "description": "test", "version": "1.0.0"}),
            )
        zip_bytes = buf.getvalue()

        metadata = json.dumps(
            {
                "org_slug": "test-org",
                "plugin_name": "my-plugin",
                "version": "1.0.0",
                "visibility": "org",
            }
        )

        resp = client.post(
            "/v1/plugins/publish",
            data={"metadata": metadata},
            files={"zip_file": ("plugin.zip", zip_bytes, "application/zip")},
            headers=auth_headers,
        )

        assert resp.status_code == 201
        # Verify insert_plugin was called with visibility="org"
        mock_insert_plugin.assert_called_once()
        call_kwargs = mock_insert_plugin.call_args
        assert call_kwargs.kwargs["visibility"] == "org"

    def test_publish_with_invalid_visibility(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_settings: MagicMock,
    ) -> None:
        """Publishing with invalid visibility returns 422."""
        import io
        import json
        import zipfile

        test_settings.google_api_key = "test-key"

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("dummy.txt", "x")
        zip_bytes = buf.getvalue()

        metadata = json.dumps(
            {
                "org_slug": "test-org",
                "plugin_name": "my-plugin",
                "version": "1.0.0",
                "visibility": "secret",
            }
        )

        resp = client.post(
            "/v1/plugins/publish",
            data={"metadata": metadata},
            files={"zip_file": ("plugin.zip", zip_bytes, "application/zip")},
            headers=auth_headers,
        )

        assert resp.status_code == 422
        assert "Invalid visibility" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Task 4: Visibility enforcement on read paths
# ---------------------------------------------------------------------------


class TestListPluginsVisibility:
    """GET /v1/plugins -- visibility filtering."""

    @patch("decision_hub.api.plugin_routes.list_user_org_ids")
    @patch("decision_hub.api.plugin_routes.fetch_paginated_plugins")
    def test_list_plugins_passes_user_org_ids_when_authenticated(
        self,
        mock_fetch: MagicMock,
        mock_org_ids: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Authenticated requests pass user_org_ids to fetch_paginated_plugins."""
        mock_org_ids.return_value = [SAMPLE_ORG_ID]
        mock_fetch.return_value = ([], 0)

        resp = client.get("/v1/plugins", headers=auth_headers)

        assert resp.status_code == 200
        mock_org_ids.assert_called_once()
        call_kwargs = mock_fetch.call_args
        assert call_kwargs.kwargs["user_org_ids"] == [SAMPLE_ORG_ID]

    @patch("decision_hub.api.plugin_routes.fetch_paginated_plugins")
    def test_list_plugins_passes_none_org_ids_when_unauthenticated(
        self,
        mock_fetch: MagicMock,
        client: TestClient,
    ) -> None:
        """Unauthenticated requests pass user_org_ids=None."""
        mock_fetch.return_value = ([], 0)

        resp = client.get("/v1/plugins")

        assert resp.status_code == 200
        call_kwargs = mock_fetch.call_args
        assert call_kwargs.kwargs["user_org_ids"] is None


class TestPluginDetailVisibility:
    """GET /v1/plugins/{org}/{name} -- visibility enforcement."""

    @patch("decision_hub.api.plugin_routes.resolve_plugin_version")
    @patch("decision_hub.api.plugin_routes.find_plugin_by_slug")
    @patch("decision_hub.api.plugin_routes.list_user_org_ids")
    def test_public_plugin_visible_to_all(
        self,
        mock_org_ids: MagicMock,
        mock_find_plugin: MagicMock,
        mock_resolve: MagicMock,
        client: TestClient,
    ) -> None:
        """Public plugins are visible to unauthenticated users."""
        org = _make_org()
        plugin = _make_plugin(org, visibility="public")
        mock_find_plugin.return_value = plugin
        mock_resolve.return_value = None

        resp = client.get("/v1/plugins/test-org/my-plugin")

        assert resp.status_code == 200

    @patch("decision_hub.api.plugin_routes.find_plugin_by_slug")
    @patch("decision_hub.api.plugin_routes.list_user_org_ids")
    def test_org_plugin_hidden_from_unauthenticated(
        self,
        mock_org_ids: MagicMock,
        mock_find_plugin: MagicMock,
        client: TestClient,
    ) -> None:
        """Org-private plugins return 404 for unauthenticated users."""
        org = _make_org()
        plugin = _make_plugin(org, visibility="org")
        mock_find_plugin.return_value = plugin

        resp = client.get("/v1/plugins/test-org/my-plugin")

        assert resp.status_code == 404

    @patch("decision_hub.api.plugin_routes.resolve_plugin_version")
    @patch("decision_hub.api.plugin_routes.find_plugin_by_slug")
    @patch("decision_hub.api.plugin_routes.list_user_org_ids")
    def test_org_plugin_visible_to_member(
        self,
        mock_org_ids: MagicMock,
        mock_find_plugin: MagicMock,
        mock_resolve: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Org-private plugins are visible to org members."""
        org = _make_org()
        plugin = _make_plugin(org, visibility="org")
        mock_org_ids.return_value = [org.id]
        mock_find_plugin.return_value = plugin
        mock_resolve.return_value = None

        resp = client.get("/v1/plugins/test-org/my-plugin", headers=auth_headers)

        assert resp.status_code == 200

    @patch("decision_hub.api.plugin_routes.find_plugin_by_slug")
    @patch("decision_hub.api.plugin_routes.list_user_org_ids")
    def test_org_plugin_hidden_from_non_member(
        self,
        mock_org_ids: MagicMock,
        mock_find_plugin: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Org-private plugins return 404 for authenticated non-members."""
        org = _make_org()
        plugin = _make_plugin(org, visibility="org")
        # User belongs to a different org
        mock_org_ids.return_value = [uuid4()]
        mock_find_plugin.return_value = plugin

        resp = client.get("/v1/plugins/test-org/my-plugin", headers=auth_headers)

        assert resp.status_code == 404


class TestResolvePluginVisibility:
    """GET /v1/plugins/{org}/{name}/resolve -- visibility enforcement."""

    @patch("decision_hub.api.plugin_routes.generate_presigned_url", return_value="https://example.com/dl")
    @patch("decision_hub.api.plugin_routes.increment_plugin_downloads")
    @patch("decision_hub.api.plugin_routes.find_plugin_by_slug")
    @patch("decision_hub.api.plugin_routes.resolve_plugin_version")
    @patch("decision_hub.api.plugin_routes.list_user_org_ids")
    def test_resolve_public_plugin_unauthenticated(
        self,
        mock_org_ids: MagicMock,
        mock_resolve: MagicMock,
        mock_find_plugin: MagicMock,
        mock_increment: MagicMock,
        mock_presigned: MagicMock,
        client: TestClient,
    ) -> None:
        """Public plugins can be resolved by unauthenticated users."""
        org = _make_org()
        plugin = _make_plugin(org, visibility="public")
        version = _make_plugin_version(plugin)
        mock_resolve.return_value = version
        mock_find_plugin.return_value = plugin

        resp = client.get("/v1/plugins/test-org/my-plugin/resolve")

        assert resp.status_code == 200
        # Verify resolve was called with user_org_ids=None
        call_kwargs = mock_resolve.call_args
        assert call_kwargs.kwargs["user_org_ids"] is None

    @patch("decision_hub.api.plugin_routes.resolve_plugin_version")
    @patch("decision_hub.api.plugin_routes.list_user_org_ids")
    def test_resolve_org_plugin_unauthenticated_returns_404(
        self,
        mock_org_ids: MagicMock,
        mock_resolve: MagicMock,
        client: TestClient,
    ) -> None:
        """Org-private plugins return 404 for unauthenticated resolve."""
        # The visibility filter in resolve_plugin_version will cause it to return None
        mock_resolve.return_value = None

        resp = client.get("/v1/plugins/test-org/my-plugin/resolve")

        assert resp.status_code == 404


class TestPluginVersionsVisibility:
    """GET /v1/plugins/{org}/{name}/versions -- visibility enforcement."""

    @patch("decision_hub.api.plugin_routes.find_plugin_by_slug")
    @patch("decision_hub.api.plugin_routes.list_user_org_ids")
    def test_versions_org_plugin_hidden_from_unauthenticated(
        self,
        mock_org_ids: MagicMock,
        mock_find_plugin: MagicMock,
        client: TestClient,
    ) -> None:
        """Org-private plugin versions are hidden from unauthenticated users."""
        org = _make_org()
        plugin = _make_plugin(org, visibility="org")
        mock_find_plugin.return_value = plugin

        resp = client.get("/v1/plugins/test-org/my-plugin/versions")

        assert resp.status_code == 404


class TestPluginAuditVisibility:
    """GET /v1/plugins/{org}/{name}/audit -- visibility enforcement."""

    @patch("decision_hub.api.plugin_routes.find_plugin_by_slug")
    @patch("decision_hub.api.plugin_routes.list_user_org_ids")
    def test_audit_org_plugin_hidden_from_unauthenticated(
        self,
        mock_org_ids: MagicMock,
        mock_find_plugin: MagicMock,
        client: TestClient,
    ) -> None:
        """Org-private plugin audit logs are hidden from unauthenticated users."""
        org = _make_org()
        plugin = _make_plugin(org, visibility="org")
        mock_find_plugin.return_value = plugin

        resp = client.get("/v1/plugins/test-org/my-plugin/audit")

        assert resp.status_code == 404
