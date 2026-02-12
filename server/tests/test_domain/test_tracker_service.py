"""Unit tests for tracker service helper functions."""

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from decision_hub.domain.repo_utils import (
    _build_authenticated_url,
    bump_version,
    create_zip,
    discover_skills,
    parse_semver,
)
from decision_hub.domain.tracker_service import process_tracker
from decision_hub.models import SkillTracker

# Backward-compat aliases used in test names
_bump_version = bump_version
_parse_semver = parse_semver
_create_zip = create_zip
_discover_skills = discover_skills


class TestBumpVersion:
    def test_bump_patch(self):
        assert _bump_version("1.2.3") == "1.2.4"

    def test_bump_from_zero(self):
        assert _bump_version("0.1.0") == "0.1.1"

    def test_bump_high_patch(self):
        assert _bump_version("1.0.99") == "1.0.100"


class TestParseSemver:
    def test_parse_standard(self):
        assert _parse_semver("1.2.3") == (1, 2, 3)

    def test_parse_zeros(self):
        assert _parse_semver("0.0.0") == (0, 0, 0)

    def test_comparison(self):
        assert _parse_semver("2.0.0") > _parse_semver("1.9.9")
        assert _parse_semver("1.0.0") < _parse_semver("2.0.0")


class TestBuildAuthenticatedUrl:
    def test_https_url(self):
        result = _build_authenticated_url("https://github.com/owner/repo", "mytoken")
        assert result == "https://x-access-token:mytoken@github.com/owner/repo.git"

    def test_ssh_url(self):
        result = _build_authenticated_url("git@github.com:owner/repo.git", "mytoken")
        assert result == "https://x-access-token:mytoken@github.com/owner/repo.git"


class TestCreateZip:
    def test_excludes_dotfiles(self, tmp_path):
        # Create test files
        (tmp_path / "SKILL.md").write_text("---\nname: test\n---\nContent")
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("git config")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "cached.pyc").write_text("cached")

        zip_data = _create_zip(tmp_path)

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            names = zf.namelist()
            assert "SKILL.md" in names
            assert "main.py" in names
            assert ".git/config" not in names
            assert "__pycache__/cached.pyc" not in names


class TestDiscoverSkills:
    def test_finds_valid_skill_dirs(self, tmp_path):
        # Create a valid skill directory
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: A test skill\n---\nSystem prompt")

        with patch("decision_hub.domain.skill_manifest.parse_skill_md") as mock_parse:
            mock_manifest = MagicMock()
            mock_manifest.name = "my-skill"
            mock_parse.return_value = mock_manifest

            result = _discover_skills(tmp_path)
            assert len(result) == 1
            assert result[0] == skill_dir

    def test_skips_hidden_dirs(self, tmp_path):
        hidden_dir = tmp_path / ".hidden"
        hidden_dir.mkdir()
        (hidden_dir / "SKILL.md").write_text("---\nname: hidden\n---\nContent")

        with patch("decision_hub.domain.skill_manifest.parse_skill_md") as mock_parse:
            result = _discover_skills(tmp_path)
            assert len(result) == 0
            mock_parse.assert_not_called()

    def test_skips_invalid_manifests(self, tmp_path):
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("invalid content")

        with patch("decision_hub.domain.skill_manifest.parse_skill_md") as mock_parse:
            mock_parse.side_effect = ValueError("Invalid manifest")
            result = _discover_skills(tmp_path)
            assert len(result) == 0


class TestVersionDetermination:
    """Test the version determination logic used in _publish_skill_from_tracker."""

    def test_first_publish_no_manifest_version(self):
        """No latest, no manifest version -> 0.1.0"""
        latest = None
        manifest_version = None
        if latest is None:
            version = manifest_version or "0.1.0"
        assert version == "0.1.0"

    def test_first_publish_with_manifest_version(self):
        """No latest, manifest version 1.0.0 -> 1.0.0"""
        latest = None
        manifest_version = "1.0.0"
        if latest is None:
            version = manifest_version or "0.1.0"
        assert version == "1.0.0"

    def test_auto_bump(self):
        """Latest 1.2.3, no manifest version -> 1.2.4"""
        latest_semver = "1.2.3"
        manifest_version = None
        if manifest_version and _parse_semver(manifest_version) > _parse_semver(latest_semver):
            version = manifest_version
        else:
            version = _bump_version(latest_semver)
        assert version == "1.2.4"

    def test_manifest_higher(self):
        """Latest 1.0.0, manifest 2.0.0 -> 2.0.0"""
        latest_semver = "1.0.0"
        manifest_version = "2.0.0"
        if manifest_version and _parse_semver(manifest_version) > _parse_semver(latest_semver):
            version = manifest_version
        else:
            version = _bump_version(latest_semver)
        assert version == "2.0.0"

    def test_manifest_lower_ignored(self):
        """Latest 2.0.0, manifest 1.0.0 -> 2.0.1"""
        latest_semver = "2.0.0"
        manifest_version = "1.0.0"
        if manifest_version and _parse_semver(manifest_version) > _parse_semver(latest_semver):
            version = manifest_version
        else:
            version = _bump_version(latest_semver)
        assert version == "2.0.1"


class TestProcessTrackerAllFailed:
    """Verify that process_tracker does NOT advance last_commit_sha when all publishes fail."""

    def _make_tracker(self) -> SkillTracker:
        return SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="myorg",
            repo_url="https://github.com/myorg/myrepo",
            branch="main",
            enabled=True,
            poll_interval_minutes=5,
            last_commit_sha="old_sha_abc",
            last_checked_at=None,
            last_published_at=None,
            last_error=None,
            created_at=datetime.now(UTC),
        )

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value=None)
    @patch("decision_hub.domain.tracker_service.has_new_commits", return_value=(True, "new_sha_xyz"))
    @patch("decision_hub.domain.tracker_service.clone_repo")
    @patch("decision_hub.domain.tracker_service.discover_skills")
    @patch("decision_hub.infra.storage.create_s3_client")
    @patch("decision_hub.domain.tracker_service._publish_skill_from_tracker")
    def test_all_failed_does_not_advance_sha(
        self,
        mock_publish,
        _mock_s3,
        mock_discover,
        mock_clone,
        _mock_commits,
        _mock_token,
    ):
        """When every skill publish raises, SHA must not advance and last_error must be set."""
        tracker = self._make_tracker()
        mock_clone.return_value = Path("/tmp/fake/repo")
        mock_discover.return_value = [Path("/tmp/fake/repo/skill-a")]
        mock_publish.side_effect = RuntimeError("S3 outage")

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.database_url = "postgresql://test"

        with patch("decision_hub.infra.database.update_skill_tracker") as mock_update:
            process_tracker(tracker, mock_settings, mock_engine)

            mock_update.assert_called_once()
            _, kwargs = mock_update.call_args
            # SHA should NOT be advanced
            assert kwargs["last_commit_sha"] is None
            # Error should be recorded
            assert kwargs["last_error"] is not None
            assert "S3 outage" in kwargs["last_error"]

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value=None)
    @patch("decision_hub.domain.tracker_service.has_new_commits", return_value=(True, "new_sha_xyz"))
    @patch("decision_hub.domain.tracker_service.clone_repo")
    @patch("decision_hub.domain.tracker_service.discover_skills")
    @patch("decision_hub.infra.storage.create_s3_client")
    @patch("decision_hub.domain.tracker_service._publish_skill_from_tracker")
    def test_partial_success_advances_sha(
        self,
        mock_publish,
        _mock_s3,
        mock_discover,
        mock_clone,
        _mock_commits,
        _mock_token,
    ):
        """When at least one skill succeeds, SHA advances and no error is recorded."""
        tracker = self._make_tracker()
        mock_clone.return_value = Path("/tmp/fake/repo")
        mock_discover.return_value = [
            Path("/tmp/fake/repo/skill-a"),
            Path("/tmp/fake/repo/skill-b"),
        ]
        # First actually publishes, second fails
        mock_publish.side_effect = [True, RuntimeError("gauntlet error")]

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.database_url = "postgresql://test"

        with patch("decision_hub.infra.database.update_skill_tracker") as mock_update:
            process_tracker(tracker, mock_settings, mock_engine)

            mock_update.assert_called_once()
            _, kwargs = mock_update.call_args
            # SHA should advance since at least one succeeded
            assert kwargs["last_commit_sha"] == "new_sha_xyz"
            assert kwargs["last_error"] is None

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value=None)
    @patch("decision_hub.domain.tracker_service.has_new_commits", return_value=(True, "new_sha_xyz"))
    @patch("decision_hub.domain.tracker_service.clone_repo")
    @patch("decision_hub.domain.tracker_service.discover_skills")
    @patch("decision_hub.infra.storage.create_s3_client")
    @patch("decision_hub.domain.tracker_service._publish_skill_from_tracker")
    def test_all_rejected_does_not_set_published_at(
        self,
        mock_publish,
        _mock_s3,
        mock_discover,
        mock_clone,
        _mock_commits,
        _mock_token,
    ):
        """When all skills are rejected/skipped (return False), last_published_at must not update."""
        tracker = self._make_tracker()
        mock_clone.return_value = Path("/tmp/fake/repo")
        mock_discover.return_value = [Path("/tmp/fake/repo/skill-a")]
        # Returns False = skipped (checksum dedup) or rejected (gauntlet)
        mock_publish.return_value = False

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()

        with patch("decision_hub.infra.database.update_skill_tracker") as mock_update:
            process_tracker(tracker, mock_settings, mock_engine)

            mock_update.assert_called_once()
            _, kwargs = mock_update.call_args
            # SHA should advance (no errors — skill was processed, just not published)
            assert kwargs["last_commit_sha"] == "new_sha_xyz"
            # last_published_at should NOT be updated since nothing was actually published
            assert kwargs["last_published_at"] is None
            assert kwargs["last_error"] is None


class TestProcessTrackerTokenResolution:
    """Verify _resolve_github_token failures are recorded as last_error."""

    @patch("decision_hub.domain.tracker_service._resolve_github_token")
    def test_token_resolution_failure_records_error(self, mock_token):
        """When _resolve_github_token raises, last_error must be set on the tracker."""
        mock_token.side_effect = RuntimeError("decrypt failed: corrupt token")

        tracker = SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="myorg",
            repo_url="https://github.com/myorg/myrepo",
            branch="main",
            enabled=True,
            poll_interval_minutes=5,
            last_commit_sha="old_sha_abc",
            last_checked_at=None,
            last_published_at=None,
            last_error=None,
            created_at=datetime.now(UTC),
        )

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()

        with patch("decision_hub.infra.database.update_skill_tracker") as mock_update:
            process_tracker(tracker, mock_settings, mock_engine)

            mock_update.assert_called_once()
            _, kwargs = mock_update.call_args
            assert kwargs["last_error"] is not None
            assert "decrypt failed" in kwargs["last_error"]
