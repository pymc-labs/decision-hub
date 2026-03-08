"""Tests for quarantine dedup in _publish_skill_from_tracker."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from decision_hub.domain.tracker_service import _publish_skill_from_tracker
from decision_hub.models import SkillTracker


def _make_tracker() -> SkillTracker:
    return SkillTracker(
        id=uuid4(),
        user_id=uuid4(),
        org_slug="myorg",
        repo_url="https://github.com/myorg/myrepo",
        branch="main",
        enabled=True,
        poll_interval_minutes=5,
        last_commit_sha="sha_abc",
        last_checked_at=None,
        last_published_at=None,
        last_error=None,
        created_at=datetime.now(UTC),
    )


def _mock_manifest() -> MagicMock:
    manifest = MagicMock()
    manifest.name = "my-skill"
    manifest.runtime = None
    return manifest


class TestQuarantineDedup:
    @patch("decision_hub.infra.storage.compute_checksum", return_value="abc123deadbeef")
    @patch("decision_hub.domain.tracker_service.create_zip", return_value=b"fake-zip")
    @patch("decision_hub.domain.tracker_service.parse_skill_md")
    @patch("decision_hub.infra.database.has_recent_quarantine", return_value=True)
    @patch("decision_hub.domain.publish_pipeline.execute_publish")
    def test_skips_gauntlet_when_recent_quarantine_exists(
        self,
        mock_execute_publish,
        mock_has_quarantine,
        mock_parse,
        mock_create_zip,
        mock_checksum,
        tmp_path,
    ):
        """When has_recent_quarantine returns True, should return False without calling execute_publish."""
        mock_parse.return_value = _mock_manifest()
        tracker = _make_tracker()
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_org = MagicMock()
        mock_org.id = uuid4()

        with (
            patch("decision_hub.infra.database.find_org_by_slug", return_value=mock_org),
            patch("decision_hub.infra.database.resolve_latest_version", return_value=None),
        ):
            mock_settings = MagicMock()
            mock_settings.tracker_quarantine_skip_hours = 24

            result = _publish_skill_from_tracker(
                skill_dir,
                "myorg",
                tracker,
                mock_settings,
                mock_engine,
                MagicMock(),
            )

        assert result is False
        mock_execute_publish.assert_not_called()
        mock_has_quarantine.assert_called_once()

    @patch("decision_hub.infra.storage.compute_checksum", return_value="abc123deadbeef")
    @patch("decision_hub.domain.tracker_service.create_zip", return_value=b"fake-zip")
    @patch("decision_hub.domain.tracker_service.parse_skill_md")
    @patch("decision_hub.infra.database.has_recent_quarantine", return_value=False)
    @patch("decision_hub.domain.publish_pipeline.execute_publish")
    def test_runs_gauntlet_when_no_recent_quarantine(
        self,
        mock_execute_publish,
        mock_has_quarantine,
        mock_parse,
        mock_create_zip,
        mock_checksum,
        tmp_path,
    ):
        """When has_recent_quarantine returns False, execute_publish should be called."""
        mock_parse.return_value = _mock_manifest()
        tracker = _make_tracker()
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_org = MagicMock()
        mock_org.id = uuid4()

        mock_result = MagicMock()
        mock_result.version = "0.1.0"
        mock_result.eval_status = "A"
        mock_execute_publish.return_value = mock_result

        with (
            patch("decision_hub.infra.database.find_org_by_slug", return_value=mock_org),
            patch("decision_hub.infra.database.resolve_latest_version", return_value=None),
        ):
            mock_settings = MagicMock()
            mock_settings.tracker_quarantine_skip_hours = 24

            result = _publish_skill_from_tracker(
                skill_dir,
                "myorg",
                tracker,
                mock_settings,
                mock_engine,
                MagicMock(),
            )

        assert result is True
        mock_execute_publish.assert_called_once()
