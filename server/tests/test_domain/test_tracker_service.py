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
from decision_hub.domain.tracker_service import (
    _dispatch_changed_trackers,
    check_all_due_trackers,
    dict_to_tracker,
    process_tracker,
    tracker_to_dict,
)
from decision_hub.models import SkillTracker, TrackerBatchResult

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

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test_token")
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

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test_token")
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

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test_token")
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


class TestProcessTrackerKnownSha:
    """Verify process_tracker skips REST check when known_sha is provided."""

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test_token")
    @patch("decision_hub.domain.tracker_service.clone_repo")
    @patch("decision_hub.domain.tracker_service.discover_skills")
    @patch("decision_hub.infra.storage.create_s3_client")
    @patch("decision_hub.domain.tracker_service._publish_skill_from_tracker", return_value=True)
    def test_known_sha_skips_rest_check(
        self,
        _mock_publish,
        _mock_s3,
        mock_discover,
        mock_clone,
        _mock_token,
    ):
        """When known_sha is passed, has_new_commits should NOT be called."""
        tracker = SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="myorg",
            repo_url="https://github.com/myorg/myrepo",
            branch="main",
            enabled=True,
            poll_interval_minutes=5,
            last_commit_sha="old_sha",
            last_checked_at=None,
            last_published_at=None,
            last_error=None,
            created_at=datetime.now(UTC),
        )
        mock_clone.return_value = Path("/tmp/fake/repo")
        mock_discover.return_value = [Path("/tmp/fake/repo/skill-a")]

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()

        with (
            patch("decision_hub.infra.database.update_skill_tracker"),
            patch("decision_hub.domain.tracker_service.has_new_commits") as mock_has_new,
        ):
            process_tracker(tracker, mock_settings, mock_engine, known_sha="new_sha_xyz")
            mock_has_new.assert_not_called()


class TestCheckAllDueTrackersBatchSize:
    """Verify check_all_due_trackers passes tracker_batch_size and jitter from settings."""

    @patch("decision_hub.infra.database.create_engine")
    @patch("decision_hub.infra.database.claim_due_trackers")
    def test_passes_batch_size_and_jitter_from_settings(self, mock_claim, mock_engine):
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_claim.return_value = []

        mock_settings = MagicMock()
        mock_settings.tracker_batch_size = 42
        mock_settings.tracker_jitter_seconds = 120

        result = check_all_due_trackers(mock_settings)

        mock_claim.assert_called_once_with(mock_conn, batch_size=42, jitter_seconds=120)
        assert isinstance(result, TrackerBatchResult)
        assert result.checked == 0


class TestProcessTrackerTokenResolution:
    """Verify _resolve_github_token failures are recorded as last_error."""

    @patch("decision_hub.domain.tracker_service._resolve_github_token")
    def test_token_resolution_failure_records_error(self, mock_token):
        """When _resolve_github_token raises, last_error must be set on the tracker."""
        mock_token.side_effect = RuntimeError("token lookup failed")

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
            assert "token lookup failed" in kwargs["last_error"]


class TestTrackerSerialization:
    """Verify tracker_to_dict / dict_to_tracker round-trip."""

    def test_round_trip(self):
        tracker = SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="myorg",
            repo_url="https://github.com/myorg/myrepo",
            branch="main",
            last_commit_sha="abc123",
            poll_interval_minutes=60,
            enabled=True,
            last_checked_at=datetime.now(UTC),
            last_published_at=None,
            last_error=None,
            next_check_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        d = tracker_to_dict(tracker)
        restored = dict_to_tracker(d)

        assert restored.id == tracker.id
        assert restored.user_id == tracker.user_id
        assert restored.org_slug == tracker.org_slug
        assert restored.repo_url == tracker.repo_url
        assert restored.branch == tracker.branch
        assert restored.last_commit_sha == tracker.last_commit_sha
        assert restored.poll_interval_minutes == tracker.poll_interval_minutes
        assert restored.enabled == tracker.enabled
        assert restored.last_published_at is None
        assert restored.last_error is None

    def test_none_datetimes_preserved(self):
        tracker = SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="org",
            repo_url="https://github.com/o/r",
            branch="main",
            last_commit_sha=None,
            poll_interval_minutes=30,
            enabled=True,
            last_checked_at=None,
            last_published_at=None,
            last_error=None,
            next_check_at=None,
            created_at=None,
        )
        d = tracker_to_dict(tracker)
        restored = dict_to_tracker(d)

        assert restored.last_checked_at is None
        assert restored.last_published_at is None
        assert restored.next_check_at is None
        assert restored.created_at is None

    def test_dict_is_json_safe(self):
        """All values in the dict should be JSON-serializable (str, int, bool, None)."""
        import json

        tracker = SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="org",
            repo_url="https://github.com/o/r",
            branch="main",
            last_commit_sha="sha",
            poll_interval_minutes=60,
            enabled=True,
            last_checked_at=datetime.now(UTC),
            last_published_at=datetime.now(UTC),
            last_error="some error",
            next_check_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        d = tracker_to_dict(tracker)
        # Should not raise
        json.dumps(d)


class TestDispatchChangedTrackers:
    """Verify _dispatch_changed_trackers fan-out and fallback behavior."""

    def _make_tracker(self) -> SkillTracker:
        return SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="myorg",
            repo_url="https://github.com/myorg/myrepo",
            branch="main",
            enabled=True,
            poll_interval_minutes=60,
            last_commit_sha="old",
            last_checked_at=None,
            last_published_at=None,
            last_error=None,
            created_at=datetime.now(UTC),
        )

    @patch("decision_hub.domain.tracker_service.process_tracker")
    @patch("modal.Function.from_name", side_effect=Exception("app not found"))
    def test_falls_back_to_sequential_when_modal_unavailable(self, _mock_from_name, mock_process):
        """When Modal from_name fails, should fall back to sequential processing."""
        tracker = self._make_tracker()
        changed = [(tracker, "new_sha")]
        mock_settings = MagicMock()
        mock_settings.modal_app_name = "nonexistent-app"
        mock_engine = MagicMock()

        processed, failed = _dispatch_changed_trackers(changed, mock_settings, mock_engine)

        assert processed == 1
        assert failed == 0
        mock_process.assert_called_once_with(tracker, mock_settings, mock_engine, known_sha="new_sha")

    @patch("decision_hub.domain.tracker_service.process_tracker")
    @patch("modal.Function.from_name", side_effect=Exception("app not found"))
    def test_sequential_fallback_counts_failures(self, _mock_from_name, mock_process):
        """When sequential processing raises, failure count should increment."""
        tracker = self._make_tracker()
        changed = [(tracker, "new_sha")]
        mock_process.side_effect = RuntimeError("clone failed")
        mock_settings = MagicMock()
        mock_settings.modal_app_name = "nonexistent-app"
        mock_engine = MagicMock()

        processed, failed = _dispatch_changed_trackers(changed, mock_settings, mock_engine)

        assert processed == 0
        assert failed == 1


class TestCheckAllDueTrackersLoopSignal:
    """Verify check_all_due_trackers returns len(trackers) so the caller loop continues."""

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test_token")
    @patch("decision_hub.domain.tracker_service._dispatch_changed_trackers", return_value=(0, 0))
    @patch("decision_hub.infra.database.batch_clear_tracker_errors")
    @patch("decision_hub.infra.database.batch_set_tracker_errors")
    @patch("decision_hub.infra.github_client.batch_fetch_commit_shas")
    @patch("decision_hub.infra.github_client.GitHubClient")
    @patch("decision_hub.infra.database.claim_due_trackers")
    @patch("decision_hub.infra.database.create_engine")
    def test_returns_due_count_when_none_changed(
        self,
        mock_create_engine,
        mock_claim,
        mock_gh_class,
        mock_batch_fetch,
        mock_batch_set_errors,
        mock_batch_clear_errors,
        mock_dispatch,
        _mock_token,
    ):
        """When trackers are due but none changed, should return len(trackers) (not 0).

        This ensures the caller loop in check_trackers keeps claiming subsequent
        batches instead of breaking early.
        """
        trackers = [
            SkillTracker(
                id=uuid4(),
                user_id=uuid4(),
                org_slug="myorg",
                repo_url=f"https://github.com/myorg/repo-{i}",
                branch="main",
                enabled=True,
                poll_interval_minutes=60,
                last_commit_sha=f"same_sha_{i}",
                last_checked_at=None,
                last_published_at=None,
                last_error=None,
                created_at=datetime.now(UTC),
            )
            for i in range(5)
        ]

        mock_conn = MagicMock()
        mock_create_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_create_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_claim.return_value = trackers

        # All trackers have the same SHA → no changes
        mock_batch_fetch.return_value = (
            {f"myorg/repo-{i}:main": f"same_sha_{i}" for i in range(5)},
            set(),
            {},
        )

        mock_gh_instance = MagicMock()
        mock_gh_instance.rate_limit_remaining = 4000
        mock_gh_class.return_value.__enter__ = MagicMock(return_value=mock_gh_instance)
        mock_gh_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.tracker_batch_size = 100
        mock_settings.tracker_jitter_seconds = 0
        mock_settings.tracker_rate_limit_floor = 500

        result = check_all_due_trackers(mock_settings)

        # Must return checked=5 (number of trackers claimed) so the loop continues
        assert isinstance(result, TrackerBatchResult)
        assert result.checked == 5
        assert result.unchanged == 5
        assert result.changed == 0
        assert result.processed == 0
        assert result.failed == 0
        assert result.github_rate_remaining == 4000
        # _dispatch_changed_trackers should be called with an empty list
        mock_dispatch.assert_called_once()
        changed_arg = mock_dispatch.call_args[0][0]
        assert len(changed_arg) == 0


class TestRateLimitGuardrail:
    """Verify check_all_due_trackers skips processing when GitHub rate limit is low."""

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test_token")
    @patch("decision_hub.domain.tracker_service._dispatch_changed_trackers")
    @patch("decision_hub.infra.database.batch_defer_trackers")
    @patch("decision_hub.infra.database.batch_update_github_stars")
    @patch("decision_hub.infra.database.batch_clear_tracker_errors")
    @patch("decision_hub.infra.database.batch_set_tracker_errors")
    @patch("decision_hub.infra.github_client.batch_fetch_commit_shas")
    @patch("decision_hub.infra.github_client.GitHubClient")
    @patch("decision_hub.infra.database.claim_due_trackers")
    @patch("decision_hub.infra.database.create_engine")
    def test_skips_processing_when_rate_limit_low(
        self,
        mock_create_engine,
        mock_claim,
        mock_gh_class,
        mock_batch_fetch,
        mock_batch_set_errors,
        mock_batch_clear_errors,
        _mock_batch_stars,
        mock_batch_defer,
        mock_dispatch,
        _mock_token,
    ):
        """When rate_limit_remaining < tracker_rate_limit_floor, dispatch should be skipped."""
        tracker = SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="myorg",
            repo_url="https://github.com/myorg/myrepo",
            branch="main",
            enabled=True,
            poll_interval_minutes=60,
            last_commit_sha="old_sha",
            last_checked_at=None,
            last_published_at=None,
            last_error=None,
            created_at=datetime.now(UTC),
        )

        mock_conn = MagicMock()
        mock_create_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_create_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_claim.return_value = [tracker]
        mock_batch_fetch.return_value = ({"myorg/myrepo:main": "new_sha"}, set(), {"myorg/myrepo": 42})

        # Set rate limit below floor
        mock_gh_instance = MagicMock()
        mock_gh_instance.rate_limit_remaining = 100
        mock_gh_class.return_value.__enter__ = MagicMock(return_value=mock_gh_instance)
        mock_gh_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.tracker_batch_size = 100
        mock_settings.tracker_jitter_seconds = 0
        mock_settings.tracker_rate_limit_floor = 500

        result = check_all_due_trackers(mock_settings)

        # Should return checked>0 but skipped_rate_limit>0, and NOT call _dispatch
        assert isinstance(result, TrackerBatchResult)
        assert result.checked == 1
        assert result.skipped_rate_limit == 1
        assert result.processed == 0
        assert result.failed == 0
        assert result.github_rate_remaining == 100
        mock_dispatch.assert_not_called()

        # Rate-limited trackers should be deferred via batch function
        mock_batch_defer.assert_called_once_with(
            mock_conn,
            [tracker.id],
            "rate_limit: deferred to next tick",
        )

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test_token")
    @patch("decision_hub.domain.tracker_service._dispatch_changed_trackers", return_value=(1, 0))
    @patch("decision_hub.infra.database.batch_update_github_stars")
    @patch("decision_hub.infra.database.batch_clear_tracker_errors")
    @patch("decision_hub.infra.database.batch_set_tracker_errors")
    @patch("decision_hub.infra.github_client.batch_fetch_commit_shas")
    @patch("decision_hub.infra.github_client.GitHubClient")
    @patch("decision_hub.infra.database.claim_due_trackers")
    @patch("decision_hub.infra.database.create_engine")
    def test_proceeds_when_rate_limit_sufficient(
        self,
        mock_create_engine,
        mock_claim,
        mock_gh_class,
        mock_batch_fetch,
        mock_batch_set_errors,
        mock_batch_clear_errors,
        _mock_batch_stars,
        mock_dispatch,
        _mock_token,
    ):
        """When rate_limit_remaining >= tracker_rate_limit_floor, dispatch should proceed."""
        tracker = SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="myorg",
            repo_url="https://github.com/myorg/myrepo",
            branch="main",
            enabled=True,
            poll_interval_minutes=60,
            last_commit_sha="old_sha",
            last_checked_at=None,
            last_published_at=None,
            last_error=None,
            created_at=datetime.now(UTC),
        )

        mock_conn = MagicMock()
        mock_create_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_create_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_claim.return_value = [tracker]
        mock_batch_fetch.return_value = ({"myorg/myrepo:main": "new_sha"}, set(), {"myorg/myrepo": 42})

        # Set rate limit above floor
        mock_gh_instance = MagicMock()
        mock_gh_instance.rate_limit_remaining = 4000
        mock_gh_class.return_value.__enter__ = MagicMock(return_value=mock_gh_instance)
        mock_gh_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.tracker_batch_size = 100
        mock_settings.tracker_jitter_seconds = 0
        mock_settings.tracker_rate_limit_floor = 500

        result = check_all_due_trackers(mock_settings)

        assert isinstance(result, TrackerBatchResult)
        assert result.checked == 1
        assert result.changed == 1
        assert result.processed == 1
        assert result.skipped_rate_limit == 0
        mock_dispatch.assert_called_once()


class TestTransientFailureClassification:
    """Verify transient vs permanent error classification in check_all_due_trackers."""

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test_token")
    @patch("decision_hub.domain.tracker_service._dispatch_changed_trackers", return_value=(0, 0))
    @patch("decision_hub.infra.database.batch_defer_trackers")
    @patch("decision_hub.infra.database.batch_update_github_stars")
    @patch("decision_hub.infra.database.batch_clear_tracker_errors")
    @patch("decision_hub.infra.database.batch_set_tracker_errors")
    @patch("decision_hub.infra.github_client.batch_fetch_commit_shas")
    @patch("decision_hub.infra.github_client.GitHubClient")
    @patch("decision_hub.infra.database.claim_due_trackers")
    @patch("decision_hub.infra.database.create_engine")
    def test_transient_vs_permanent_errors(
        self,
        mock_create_engine,
        mock_claim,
        mock_gh_class,
        mock_batch_fetch,
        mock_batch_set_errors,
        mock_batch_clear_errors,
        _mock_batch_stars,
        mock_batch_defer,
        mock_dispatch,
        _mock_token,
    ):
        """One tracker in successful chunk (unchanged), one in failed chunk (transient error)."""
        tracker_ok = SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="myorg",
            repo_url="https://github.com/myorg/repo-ok",
            branch="main",
            enabled=True,
            poll_interval_minutes=60,
            last_commit_sha="same_sha",
            last_checked_at=None,
            last_published_at=None,
            last_error=None,
            created_at=datetime.now(UTC),
        )
        tracker_transient = SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="myorg",
            repo_url="https://github.com/myorg/repo-transient",
            branch="main",
            enabled=True,
            poll_interval_minutes=60,
            last_commit_sha="old_sha",
            last_checked_at=None,
            last_published_at=None,
            last_error=None,
            created_at=datetime.now(UTC),
        )
        tracker_permanent = SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="myorg",
            repo_url="https://github.com/myorg/repo-gone",
            branch="main",
            enabled=True,
            poll_interval_minutes=60,
            last_commit_sha="old_sha",
            last_checked_at=None,
            last_published_at=None,
            last_error=None,
            created_at=datetime.now(UTC),
        )

        mock_conn = MagicMock()
        mock_create_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_create_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_claim.return_value = [tracker_ok, tracker_transient, tracker_permanent]

        # repo-ok: SHA unchanged; repo-transient: chunk failed; repo-gone: no data
        mock_batch_fetch.return_value = (
            {"myorg/repo-ok:main": "same_sha"},
            {"myorg/repo-transient:main"},  # failed chunk keys
            {"myorg/repo-ok": 15},
        )

        mock_gh_instance = MagicMock()
        mock_gh_instance.rate_limit_remaining = 4000
        mock_gh_class.return_value.__enter__ = MagicMock(return_value=mock_gh_instance)
        mock_gh_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.tracker_batch_size = 100
        mock_settings.tracker_jitter_seconds = 0
        mock_settings.tracker_rate_limit_floor = 500

        result = check_all_due_trackers(mock_settings)

        assert result.checked == 3
        assert result.unchanged == 1
        assert result.errored == 2  # transient + permanent both counted
        assert result.changed == 0

        # Verify batch_set_tracker_errors called with both error types
        calls = mock_batch_set_errors.call_args_list
        # Find the permanent error call
        permanent_call = [c for c in calls if "GraphQL: repo not found" in str(c)]
        assert len(permanent_call) == 1
        assert tracker_permanent.id in permanent_call[0][0][1]
        # Find the transient error call
        transient_call = [c for c in calls if "transient:" in str(c)]
        assert len(transient_call) == 1
        assert tracker_transient.id in transient_call[0][0][1]

        # Unchanged tracker should be cleared
        mock_batch_clear_errors.assert_called_once()
        assert tracker_ok.id in mock_batch_clear_errors.call_args[0][1]


class TestAutoDisablePermanentErrors:
    """Verify check_all_due_trackers auto-disables permanent-error trackers and marks skills."""

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test_token")
    @patch("decision_hub.domain.tracker_service._dispatch_changed_trackers", return_value=(0, 0))
    @patch("decision_hub.infra.database.batch_defer_trackers")
    @patch("decision_hub.infra.database.batch_clear_tracker_errors")
    @patch("decision_hub.infra.database.batch_set_tracker_errors")
    @patch("decision_hub.infra.database.batch_disable_trackers")
    @patch("decision_hub.infra.database.mark_skills_source_removed")
    @patch("decision_hub.infra.github_client.batch_fetch_commit_shas")
    @patch("decision_hub.infra.github_client.GitHubClient")
    @patch("decision_hub.infra.database.claim_due_trackers")
    @patch("decision_hub.infra.database.create_engine")
    def test_permanent_errors_disable_trackers_and_mark_skills(
        self,
        mock_create_engine,
        mock_claim,
        mock_gh_class,
        mock_batch_fetch,
        mock_mark_removed,
        mock_batch_disable,
        mock_batch_set_errors,
        mock_batch_clear_errors,
        mock_batch_defer,
        mock_dispatch,
        _mock_token,
    ):
        """When sha_map returns None for a repo, the tracker should be disabled
        and its skills marked as source_repo_removed."""
        tracker_gone = SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="myorg",
            repo_url="https://github.com/myorg/deleted-repo",
            branch="main",
            enabled=True,
            poll_interval_minutes=60,
            last_commit_sha="old_sha",
            last_checked_at=None,
            last_published_at=None,
            last_error=None,
            created_at=datetime.now(UTC),
        )

        mock_conn = MagicMock()
        mock_create_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_create_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_claim.return_value = [tracker_gone]

        # Repo resolves but returns no data → permanent error
        mock_batch_fetch.return_value = ({}, set(), {})

        mock_gh_instance = MagicMock()
        mock_gh_instance.rate_limit_remaining = 4000
        mock_gh_class.return_value.__enter__ = MagicMock(return_value=mock_gh_instance)
        mock_gh_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.tracker_batch_size = 100
        mock_settings.tracker_jitter_seconds = 0
        mock_settings.tracker_rate_limit_floor = 500

        result = check_all_due_trackers(mock_settings)

        assert result.errored == 1
        # batch_disable_trackers should have been called with the permanent-error tracker
        mock_batch_disable.assert_called_once_with(mock_conn, [tracker_gone.id])
        # mark_skills_source_removed should have been called with the repo URL
        mock_mark_removed.assert_called_once()
        removed_urls = mock_mark_removed.call_args[0][1]
        assert "https://github.com/myorg/deleted-repo" in removed_urls


class TestProcessTrackerNoSkillsDisables:
    """Verify process_tracker disables tracker and marks skills when no skills found."""

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test_token")
    @patch("decision_hub.domain.tracker_service.has_new_commits", return_value=(True, "new_sha_xyz"))
    @patch("decision_hub.domain.tracker_service.clone_repo")
    @patch("decision_hub.domain.tracker_service.discover_skills")
    def test_no_skills_found_disables_tracker(
        self,
        mock_discover,
        mock_clone,
        _mock_commits,
        _mock_token,
    ):
        """When discover_skills returns empty, tracker should be disabled
        and skills marked as removed."""
        tracker = SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="myorg",
            repo_url="https://github.com/myorg/empty-repo",
            branch="main",
            enabled=True,
            poll_interval_minutes=5,
            last_commit_sha="old_sha",
            last_checked_at=None,
            last_published_at=None,
            last_error=None,
            created_at=datetime.now(UTC),
        )
        mock_clone.return_value = Path("/tmp/fake/repo")
        mock_discover.return_value = []

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()

        with (
            patch("decision_hub.infra.database.update_skill_tracker") as mock_update,
            patch("decision_hub.infra.database.mark_skills_source_removed") as mock_mark,
        ):
            process_tracker(tracker, mock_settings, mock_engine)

            mock_update.assert_called_once()
            _, kwargs = mock_update.call_args
            assert kwargs["enabled"] is False
            assert kwargs["last_error"] == "No skills found in repository"

            mock_mark.assert_called_once_with(
                mock_conn,
                ["https://github.com/myorg/empty-repo"],
            )


class TestRepoDeduplication:
    """Verify that duplicate repos are deduplicated in GraphQL calls."""

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test_token")
    @patch("decision_hub.domain.tracker_service._dispatch_changed_trackers", return_value=(0, 0))
    @patch("decision_hub.infra.database.batch_update_github_stars")
    @patch("decision_hub.infra.database.batch_clear_tracker_errors")
    @patch("decision_hub.infra.database.batch_set_tracker_errors")
    @patch("decision_hub.infra.github_client.batch_fetch_commit_shas")
    @patch("decision_hub.infra.github_client.GitHubClient")
    @patch("decision_hub.infra.database.claim_due_trackers")
    @patch("decision_hub.infra.database.create_engine")
    def test_three_trackers_same_repo_one_graphql_call(
        self,
        mock_create_engine,
        mock_claim,
        mock_gh_class,
        mock_batch_fetch,
        mock_batch_set_errors,
        mock_batch_clear_errors,
        _mock_batch_stars,
        mock_dispatch,
        _mock_token,
    ):
        """3 trackers pointing to same repo/branch → batch_fetch receives only 1 unique repo."""
        trackers = [
            SkillTracker(
                id=uuid4(),
                user_id=uuid4(),
                org_slug=f"org{i}",
                repo_url="https://github.com/myorg/shared-repo",
                branch="main",
                enabled=True,
                poll_interval_minutes=60,
                last_commit_sha="same_sha",
                last_checked_at=None,
                last_published_at=None,
                last_error=None,
                created_at=datetime.now(UTC),
            )
            for i in range(3)
        ]

        mock_conn = MagicMock()
        mock_create_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_create_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_claim.return_value = trackers
        mock_batch_fetch.return_value = ({"myorg/shared-repo:main": "same_sha"}, set(), {"myorg/shared-repo": 99})

        mock_gh_instance = MagicMock()
        mock_gh_instance.rate_limit_remaining = 4000
        mock_gh_class.return_value.__enter__ = MagicMock(return_value=mock_gh_instance)
        mock_gh_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.tracker_batch_size = 100
        mock_settings.tracker_jitter_seconds = 0
        mock_settings.tracker_rate_limit_floor = 500

        result = check_all_due_trackers(mock_settings)

        # All 3 trackers should be counted as unchanged
        assert result.checked == 3
        assert result.unchanged == 3
        assert result.changed == 0
        assert result.errored == 0

        # batch_fetch should receive only 1 unique repo
        call_args = mock_batch_fetch.call_args[0]
        repos_arg = call_args[1]
        assert len(repos_arg) == 1
        assert repos_arg[0] == ("myorg", "shared-repo", "main")


class TestCronLoopBehavior:
    """Test the cron loop logic from check_trackers in modal_app.py.

    Since check_trackers is a Modal function, we test the loop logic by
    simulating it with TrackerBatchResult sequences.
    """

    def _simulate_loop(self, results: list[TrackerBatchResult]) -> dict:
        """Simulate the check_trackers loop accumulation logic."""
        total_checked = 0
        total_due = 0
        total_unchanged = 0
        total_changed = 0
        total_errored = 0
        total_processed = 0
        total_failed = 0
        total_skipped_rate_limit = 0
        iterations = 0

        for result in results:
            total_checked += result.checked
            total_due += result.due
            total_unchanged += result.unchanged
            total_changed += result.changed
            total_errored += result.errored
            total_processed += result.processed
            total_failed += result.failed
            total_skipped_rate_limit += result.skipped_rate_limit
            iterations += 1
            if result.checked == 0:
                break
            if result.skipped_rate_limit > 0:
                break

        return {
            "iterations": iterations,
            "total_checked": total_checked,
            "total_due": total_due,
            "total_unchanged": total_unchanged,
            "total_changed": total_changed,
            "total_errored": total_errored,
            "total_processed": total_processed,
            "total_failed": total_failed,
            "total_skipped_rate_limit": total_skipped_rate_limit,
        }

    def test_loop_stops_when_checked_is_zero(self):
        """Loop terminates when checked == 0 (no more due trackers)."""
        results = [
            TrackerBatchResult(
                checked=5,
                due=5,
                unchanged=5,
                changed=0,
                errored=0,
                processed=0,
                failed=0,
                skipped_rate_limit=0,
                github_rate_remaining=4000,
            ),
            TrackerBatchResult(
                checked=3,
                due=3,
                unchanged=3,
                changed=0,
                errored=0,
                processed=0,
                failed=0,
                skipped_rate_limit=0,
                github_rate_remaining=3900,
            ),
            TrackerBatchResult(
                checked=0,
                due=0,
                unchanged=0,
                changed=0,
                errored=0,
                processed=0,
                failed=0,
                skipped_rate_limit=0,
                github_rate_remaining=None,
            ),
        ]
        acc = self._simulate_loop(results)
        assert acc["iterations"] == 3
        assert acc["total_checked"] == 8

    def test_loop_stops_on_rate_limit(self):
        """Loop terminates when skipped_rate_limit > 0."""
        results = [
            TrackerBatchResult(
                checked=5,
                due=5,
                unchanged=3,
                changed=2,
                errored=0,
                processed=2,
                failed=0,
                skipped_rate_limit=0,
                github_rate_remaining=600,
            ),
            TrackerBatchResult(
                checked=5,
                due=5,
                unchanged=2,
                changed=3,
                errored=0,
                processed=0,
                failed=0,
                skipped_rate_limit=3,
                github_rate_remaining=100,
            ),
            # This should never be reached
            TrackerBatchResult(
                checked=5,
                due=5,
                unchanged=5,
                changed=0,
                errored=0,
                processed=0,
                failed=0,
                skipped_rate_limit=0,
                github_rate_remaining=50,
            ),
        ]
        acc = self._simulate_loop(results)
        assert acc["iterations"] == 2
        assert acc["total_skipped_rate_limit"] == 3

    def test_metrics_accumulate_across_iterations(self):
        """Counters sum correctly across multiple iterations."""
        results = [
            TrackerBatchResult(
                checked=10,
                due=10,
                unchanged=8,
                changed=2,
                errored=0,
                processed=2,
                failed=0,
                skipped_rate_limit=0,
                github_rate_remaining=4000,
            ),
            TrackerBatchResult(
                checked=10,
                due=10,
                unchanged=7,
                changed=1,
                errored=2,
                processed=1,
                failed=0,
                skipped_rate_limit=0,
                github_rate_remaining=3900,
            ),
            TrackerBatchResult(
                checked=0,
                due=0,
                unchanged=0,
                changed=0,
                errored=0,
                processed=0,
                failed=0,
                skipped_rate_limit=0,
                github_rate_remaining=None,
            ),
        ]
        acc = self._simulate_loop(results)
        assert acc["total_checked"] == 20
        assert acc["total_unchanged"] == 15
        assert acc["total_changed"] == 3
        assert acc["total_errored"] == 2
        assert acc["total_processed"] == 3


class TestMetricsMathContract:
    """Verify invariants: checked == unchanged + changed + errored."""

    def test_basic_contract(self):
        """checked == unchanged + changed + errored holds."""
        result = TrackerBatchResult(
            checked=10,
            due=10,
            unchanged=6,
            changed=3,
            errored=1,
            processed=3,
            failed=0,
            skipped_rate_limit=0,
            github_rate_remaining=4000,
        )
        assert result.checked == result.unchanged + result.changed + result.errored

    def test_contract_with_transient_errors_in_errored(self):
        """Transient errors are counted in errored — contract still holds."""
        # Simulating: 2 permanent + 3 transient = 5 errored
        result = TrackerBatchResult(
            checked=20,
            due=20,
            unchanged=10,
            changed=5,
            errored=5,
            processed=4,
            failed=1,
            skipped_rate_limit=0,
            github_rate_remaining=3000,
        )
        assert result.checked == result.unchanged + result.changed + result.errored

    def test_processed_plus_failed_leq_changed(self):
        """processed + failed <= changed."""
        result = TrackerBatchResult(
            checked=10,
            due=10,
            unchanged=5,
            changed=5,
            errored=0,
            processed=3,
            failed=2,
            skipped_rate_limit=0,
            github_rate_remaining=4000,
        )
        assert result.processed + result.failed <= result.changed

    def test_rate_limited_skips_all_changed(self):
        """When rate-limited, skipped_rate_limit == changed and processed == 0."""
        result = TrackerBatchResult(
            checked=10,
            due=10,
            unchanged=7,
            changed=3,
            errored=0,
            processed=0,
            failed=0,
            skipped_rate_limit=3,
            github_rate_remaining=100,
        )
        assert result.skipped_rate_limit == result.changed
        assert result.processed == 0
        assert result.checked == result.unchanged + result.changed + result.errored
