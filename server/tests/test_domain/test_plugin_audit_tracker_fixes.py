"""Tests for plugin audit log FK fix, tracker self-disabling fix, and audit query leak fix.

Task 1: insert_audit_log receives plugin_version_id (not version_id) for plugins.
Task 2: update_skill_tracker receives kind="plugin" after plugin publish.
Task 9: find_plugin_audit_logs filters on plugin_name IS NOT NULL.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from decision_hub.models import AuditLogEntry, Plugin, PluginVersion, SkillTracker
from dhub_core.plugin_manifest import PluginManifest

# ---------------------------------------------------------------------------
# Task 1: Audit log FK fix — plugin publish uses plugin_version_id
# ---------------------------------------------------------------------------


class TestPluginAuditLogFKFix:
    """Verify that plugin publishes write plugin_version_id, not version_id."""

    @patch("decision_hub.domain.plugin_publish_pipeline.deprecate_skills_by_repo_url", return_value=0)
    @patch("decision_hub.domain.plugin_publish_pipeline.upload_skill_zip")
    @patch("decision_hub.domain.plugin_publish_pipeline.insert_audit_log")
    @patch("decision_hub.domain.plugin_publish_pipeline.insert_plugin_version")
    @patch("decision_hub.domain.plugin_publish_pipeline.find_plugin_version", return_value=None)
    @patch("decision_hub.domain.plugin_publish_pipeline.update_plugin_component_counts")
    @patch("decision_hub.domain.plugin_publish_pipeline.update_plugin_category")
    @patch("decision_hub.domain.plugin_publish_pipeline.update_plugin_description")
    @patch("decision_hub.domain.plugin_publish_pipeline.find_plugin")
    @patch("decision_hub.domain.plugin_publish_pipeline.classify_skill_category", return_value="utilities")
    @patch("decision_hub.domain.plugin_publish_pipeline.run_plugin_static_checks")
    @patch("decision_hub.domain.plugin_publish_pipeline.extract_plugin_for_evaluation")
    @patch("decision_hub.domain.plugin_publish_pipeline.parse_plugin_manifest")
    @patch("decision_hub.domain.plugin_publish_pipeline.extract_plugin_to_dir")
    @patch("decision_hub.infra.embeddings.generate_and_store_plugin_embedding")
    def test_acceptance_audit_uses_plugin_version_id(
        self,
        _mock_embedding,
        _mock_extract_dir,
        mock_parse_manifest,
        mock_extract_eval,
        mock_static_checks,
        _mock_classify,
        mock_find_plugin,
        _mock_update_desc,
        _mock_update_cat,
        _mock_update_counts,
        _mock_find_version,
        mock_insert_version,
        mock_insert_audit,
        _mock_upload,
        _mock_deprecate,
    ):
        """On successful plugin publish, insert_audit_log must receive
        plugin_version_id (pointing at plugin_versions) instead of
        version_id (which points at the skill versions table).
        """
        from decision_hub.domain.plugin_publish_pipeline import execute_plugin_publish

        plugin_id = uuid4()
        plugin_version_id = uuid4()

        # Use a real PluginManifest so dataclasses.asdict works
        manifest = PluginManifest(
            name="my-plugin",
            description="desc",
            version="1.0.0",
            author_name="author",
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
        mock_parse_manifest.return_value = manifest

        mock_extract_eval.return_value = ([], [])

        # Gauntlet passes
        report = MagicMock()
        report.passed = True
        report.grade = "A"
        report.results = []
        report.gauntlet_summary = "all good"
        mock_static_checks.return_value = report

        # Existing plugin
        plugin = Plugin(id=plugin_id, org_id=uuid4(), name="my-plugin", description="desc")
        mock_find_plugin.return_value = plugin

        # Version record
        version_record = PluginVersion(
            id=plugin_version_id,
            plugin_id=plugin_id,
            semver="1.0.0",
            s3_key="plugins/org/my-plugin/1.0.0.zip",
            checksum="abc",
            plugin_manifest=None,
            runtime_config=None,
            eval_status="A",
        )
        mock_insert_version.return_value = version_record

        mock_conn = MagicMock()
        mock_audit_entry = MagicMock(spec=AuditLogEntry)
        mock_insert_audit.return_value = mock_audit_entry

        execute_plugin_publish(
            conn=mock_conn,
            s3_client=MagicMock(),
            settings=MagicMock(),
            org_id=uuid4(),
            org_slug="test-org",
            plugin_name="my-plugin",
            version="1.0.0",
            checksum="abc",
            file_bytes=b"fakebytes",
            publisher="user1",
        )

        # Verify the acceptance audit log call
        mock_insert_audit.assert_called_once()
        _, kwargs = mock_insert_audit.call_args
        # Must NOT pass version_id (skill FK)
        assert "version_id" not in kwargs or kwargs.get("version_id") is None
        # Must pass plugin_version_id
        assert kwargs["plugin_version_id"] == plugin_version_id
        # Must pass plugin_id and plugin_name
        assert kwargs["plugin_id"] == plugin_id
        assert kwargs["plugin_name"] == "my-plugin"

    @patch("decision_hub.domain.plugin_publish_pipeline.upload_skill_zip")
    @patch("decision_hub.domain.plugin_publish_pipeline.insert_audit_log")
    @patch("decision_hub.domain.plugin_publish_pipeline.run_plugin_static_checks")
    @patch("decision_hub.domain.plugin_publish_pipeline.extract_plugin_for_evaluation")
    @patch("decision_hub.domain.plugin_publish_pipeline.parse_plugin_manifest")
    @patch("decision_hub.domain.plugin_publish_pipeline.extract_plugin_to_dir")
    def test_rejection_audit_includes_plugin_name(
        self,
        _mock_extract_dir,
        mock_parse_manifest,
        mock_extract_eval,
        mock_static_checks,
        mock_insert_audit,
        _mock_upload,
    ):
        """On gauntlet rejection, audit log must include plugin_name."""
        from decision_hub.domain.plugin_publish_pipeline import execute_plugin_publish
        from decision_hub.domain.publish_pipeline import GauntletRejectionError

        manifest = MagicMock()
        manifest.name = "bad-plugin"
        manifest.description = "desc"
        manifest.version = "1.0.0"
        manifest.hooks = ()
        mock_parse_manifest.return_value = manifest

        mock_extract_eval.return_value = ([], [])

        # Gauntlet rejects
        report = MagicMock()
        report.passed = False
        report.grade = "F"
        report.summary = "Dangerous hooks"
        from decision_hub.domain.gauntlet import EvalResult

        report.results = [EvalResult(check_name="hook_check", severity="fail", message="bad hook")]
        mock_static_checks.return_value = report

        mock_conn = MagicMock()
        mock_audit_entry = MagicMock(spec=AuditLogEntry)
        mock_insert_audit.return_value = mock_audit_entry

        with pytest.raises(GauntletRejectionError):
            execute_plugin_publish(
                conn=mock_conn,
                s3_client=MagicMock(),
                settings=MagicMock(),
                org_id=uuid4(),
                org_slug="test-org",
                plugin_name="bad-plugin",
                version="1.0.0",
                checksum="abc",
                file_bytes=b"fakebytes",
                publisher="user1",
            )

        mock_insert_audit.assert_called_once()
        _, kwargs = mock_insert_audit.call_args
        # Rejection audit must NOT have version_id (no version was created)
        assert kwargs.get("version_id") is None
        # Must tag with plugin_name
        assert kwargs["plugin_name"] == "bad-plugin"


# ---------------------------------------------------------------------------
# Task 2: Tracker self-disabling fix — kind="plugin" after publish
# ---------------------------------------------------------------------------


class TestTrackerKindUpdate:
    """Verify tracker is updated with kind='plugin' after successful plugin publish."""

    @staticmethod
    def _make_tracker(kind: str = "skill") -> SkillTracker:
        return SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="test-org",
            repo_url="https://github.com/test-org/plugin-repo",
            branch="main",
            last_commit_sha="old_sha",
            poll_interval_minutes=5,
            enabled=True,
            last_checked_at=None,
            last_published_at=None,
            last_error=None,
            kind=kind,
            created_at=datetime.now(UTC),
        )

    def test_update_skill_tracker_called_with_kind_plugin(self):
        """After successful plugin publish, update_skill_tracker must be called with kind='plugin'."""
        from decision_hub.domain.plugin_publish_pipeline import PluginPublishResult
        from decision_hub.domain.tracker_service import _publish_plugin_from_tracker

        tracker = self._make_tracker()

        publish_result = PluginPublishResult(
            plugin_id=uuid4(),
            version_id=uuid4(),
            version="1.0.0",
            s3_key="plugins/test-org/my-plugin/1.0.0.zip",
            checksum="sha256abc",
            eval_status="A",
            deprecated_skills_count=0,
        )

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()

        manifest = MagicMock()
        manifest.name = "my-plugin"
        manifest.version = "1.0.0"

        with (
            patch("decision_hub.domain.tracker_service.create_zip", return_value=b"zipdata"),
            patch("decision_hub.infra.storage.compute_checksum", return_value="sha256abc"),
            patch(
                "decision_hub.domain.plugin_publish_pipeline.execute_plugin_publish",
                return_value=publish_result,
            ),
            patch("decision_hub.infra.database.disable_skill_trackers_for_repo", return_value=0),
            patch("decision_hub.infra.database.update_skill_tracker") as mock_update_tracker,
            patch("dhub_core.plugin_manifest.parse_plugin_manifest", return_value=manifest),
            patch("decision_hub.domain.tracker_service._resolve_org_id", return_value=uuid4()),
        ):
            _publish_plugin_from_tracker(
                repo_root=Path("/tmp/fake"),
                org_slug="test-org",
                tracker=tracker,
                settings=mock_settings,
                engine=mock_engine,
                s3_client=MagicMock(),
                current_sha="new_sha_xyz",
            )

            mock_update_tracker.assert_called_once()
            _, kwargs = mock_update_tracker.call_args
            assert kwargs["kind"] == "plugin"
            assert kwargs["last_commit_sha"] == "new_sha_xyz"
            assert kwargs["last_error"] is None


# ---------------------------------------------------------------------------
# Task 9: Plugin audit query leak fix — filter on plugin_name IS NOT NULL
# ---------------------------------------------------------------------------


class TestPluginAuditQueryLeak:
    """Verify find_plugin_audit_logs only returns plugin-tagged entries."""

    def test_find_plugin_audit_logs_filters_on_plugin_name_not_null(self):
        """The SQL query must include plugin_name IS NOT NULL to prevent skill leakage."""
        # We test by inspecting the compiled SQL, which avoids needing a real DB.

        from decision_hub.infra.database import find_plugin_audit_logs

        mock_conn = MagicMock()
        mock_conn.execute.return_value.all.return_value = []

        find_plugin_audit_logs(mock_conn, "my-plugin", "test-org")

        # Inspect the SQL statement passed to execute
        call_args = mock_conn.execute.call_args
        stmt = call_args[0][0]
        # Compile the statement to SQL text
        compiled = stmt.compile(compile_kwargs={"literal_binds": True})
        sql_text = str(compiled)

        # Must contain the plugin_name IS NOT NULL filter
        assert "plugin_name IS NOT NULL" in sql_text
