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
        mock_batch_fetch.return_value = ({"myorg/myrepo:main": "new_sha"}, set(), {"myorg/myrepo": 42}, {})

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
        mock_batch_fetch.return_value = ({"myorg/myrepo:main": "new_sha"}, set(), {"myorg/myrepo": 42}, {})

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
        mock_settings.tracker_circuit_breaker_ratio = 0.5

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
    """Verify check_all_due_trackers uses consecutive failure tracking before disabling."""

    def _make_tracker(self, **overrides):
        defaults = dict(
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
        defaults.update(overrides)
        return SkillTracker(**defaults)

    def _setup_mocks(self, mock_create_engine, mock_claim, mock_gh_class, mock_batch_fetch, trackers):
        mock_conn = MagicMock()
        mock_create_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_create_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_claim.return_value = trackers
        # All repos resolve but return no data → permanent error
        mock_batch_fetch.return_value = ({}, set(), {}, {})
        mock_gh_instance = MagicMock()
        mock_gh_instance.rate_limit_remaining = 4000
        mock_gh_class.return_value.__enter__ = MagicMock(return_value=mock_gh_instance)
        mock_gh_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_settings = MagicMock()
        mock_settings.tracker_batch_size = 100
        mock_settings.tracker_jitter_seconds = 0
        mock_settings.tracker_rate_limit_floor = 500
        mock_settings.tracker_permanent_failure_threshold = 10
        mock_settings.tracker_circuit_breaker_ratio = 1.0  # disable circuit breaker for these tests
        return mock_conn, mock_settings

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test_token")
    @patch("decision_hub.domain.tracker_service._dispatch_changed_trackers", return_value=(0, 0))
    @patch("decision_hub.infra.database.batch_defer_trackers")
    @patch("decision_hub.infra.database.batch_clear_tracker_errors")
    @patch("decision_hub.infra.database.batch_set_tracker_errors")
    @patch("decision_hub.infra.database.batch_disable_trackers")
    @patch("decision_hub.infra.database.batch_increment_permanent_failures")
    @patch("decision_hub.infra.database.mark_skills_source_removed")
    @patch("decision_hub.infra.github_client.batch_fetch_commit_shas")
    @patch("decision_hub.infra.github_client.GitHubClient")
    @patch("decision_hub.infra.database.claim_due_trackers")
    @patch("decision_hub.infra.database.create_engine")
    def test_single_failure_increments_counter_but_does_not_disable(
        self,
        mock_create_engine,
        mock_claim,
        mock_gh_class,
        mock_batch_fetch,
        mock_mark_removed,
        mock_increment,
        mock_batch_disable,
        mock_batch_set_errors,
        mock_batch_clear_errors,
        mock_batch_defer,
        mock_dispatch,
        _mock_token,
    ):
        """A single permanent error should increment the counter but NOT disable
        the tracker or mark skills as removed."""
        tracker = self._make_tracker()
        mock_conn, mock_settings = self._setup_mocks(
            mock_create_engine,
            mock_claim,
            mock_gh_class,
            mock_batch_fetch,
            [tracker],
        )
        # Counter below threshold — no IDs returned
        mock_increment.return_value = []

        result = check_all_due_trackers(mock_settings)

        assert result.errored == 1
        mock_increment.assert_called_once_with(mock_conn, [tracker.id], threshold=10)
        mock_batch_disable.assert_not_called()
        mock_mark_removed.assert_not_called()

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test_token")
    @patch("decision_hub.domain.tracker_service._dispatch_changed_trackers", return_value=(0, 0))
    @patch("decision_hub.infra.database.batch_defer_trackers")
    @patch("decision_hub.infra.database.batch_clear_tracker_errors")
    @patch("decision_hub.infra.database.batch_set_tracker_errors")
    @patch("decision_hub.infra.database.batch_disable_trackers")
    @patch("decision_hub.infra.database.batch_increment_permanent_failures")
    @patch("decision_hub.infra.database.mark_skills_source_removed")
    @patch("decision_hub.infra.github_client.batch_fetch_commit_shas")
    @patch("decision_hub.infra.github_client.GitHubClient")
    @patch("decision_hub.infra.database.claim_due_trackers")
    @patch("decision_hub.infra.database.create_engine")
    def test_threshold_crossed_disables_and_marks_removed_when_rest_confirms_404(
        self,
        mock_create_engine,
        mock_claim,
        mock_gh_class,
        mock_batch_fetch,
        mock_mark_removed,
        mock_increment,
        mock_batch_disable,
        mock_batch_set_errors,
        mock_batch_clear_errors,
        mock_batch_defer,
        mock_dispatch,
        _mock_token,
    ):
        """When consecutive failures cross the threshold AND REST confirms 404,
        the tracker should be disabled and skills marked as removed."""
        tracker = self._make_tracker()
        mock_conn, mock_settings = self._setup_mocks(
            mock_create_engine,
            mock_claim,
            mock_gh_class,
            mock_batch_fetch,
            [tracker],
        )
        # Counter crossed threshold — return this tracker's ID
        mock_increment.return_value = [tracker.id]

        # REST verification returns 404 — repo is truly gone
        mock_gh_instance = mock_gh_class.return_value.__enter__.return_value
        mock_rest_resp = MagicMock()
        mock_rest_resp.status_code = 404
        mock_gh_instance.get.return_value = mock_rest_resp

        result = check_all_due_trackers(mock_settings)

        assert result.errored == 1
        mock_increment.assert_called_once_with(mock_conn, [tracker.id], threshold=10)
        mock_batch_disable.assert_called_once_with(mock_conn, [tracker.id])
        mock_mark_removed.assert_called_once()
        removed_urls = mock_mark_removed.call_args[0][1]
        assert "https://github.com/myorg/deleted-repo" in removed_urls
        # REST was called to verify
        mock_gh_instance.get.assert_called_once_with("/repos/myorg/deleted-repo")

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test_token")
    @patch("decision_hub.domain.tracker_service._dispatch_changed_trackers", return_value=(0, 0))
    @patch("decision_hub.infra.database.batch_defer_trackers")
    @patch("decision_hub.infra.database.batch_clear_tracker_errors")
    @patch("decision_hub.infra.database.batch_set_tracker_errors")
    @patch("decision_hub.infra.database.batch_disable_trackers")
    @patch("decision_hub.infra.database.batch_increment_permanent_failures")
    @patch("decision_hub.infra.database.mark_skills_source_removed")
    @patch("decision_hub.infra.github_client.batch_fetch_commit_shas")
    @patch("decision_hub.infra.github_client.GitHubClient")
    @patch("decision_hub.infra.database.claim_due_trackers")
    @patch("decision_hub.infra.database.create_engine")
    def test_threshold_crossed_but_rest_says_alive_skips_removal(
        self,
        mock_create_engine,
        mock_claim,
        mock_gh_class,
        mock_batch_fetch,
        mock_mark_removed,
        mock_increment,
        mock_batch_disable,
        mock_batch_set_errors,
        mock_batch_clear_errors,
        mock_batch_defer,
        mock_dispatch,
        _mock_token,
    ):
        """When consecutive failures cross the threshold but REST returns 200,
        the tracker should be disabled but skills should NOT be marked removed."""
        tracker = self._make_tracker()
        mock_conn, mock_settings = self._setup_mocks(
            mock_create_engine,
            mock_claim,
            mock_gh_class,
            mock_batch_fetch,
            [tracker],
        )
        mock_increment.return_value = [tracker.id]

        # REST verification returns 200 — repo still exists
        mock_gh_instance = mock_gh_class.return_value.__enter__.return_value
        mock_rest_resp = MagicMock()
        mock_rest_resp.status_code = 200
        mock_gh_instance.get.return_value = mock_rest_resp

        result = check_all_due_trackers(mock_settings)

        assert result.errored == 1
        mock_batch_disable.assert_called_once_with(mock_conn, [tracker.id])
        # mark_skills_source_removed should be called with an EMPTY list
        mock_mark_removed.assert_called_once_with(mock_conn, [])
        mock_gh_instance.get.assert_called_once_with("/repos/myorg/deleted-repo")


class TestVerifyReposRemoved:
    """Unit tests for _verify_repos_removed."""

    def test_filters_to_only_404_repos(self):
        from decision_hub.domain.tracker_service import _verify_repos_removed

        mock_gh = MagicMock()
        resp_404 = MagicMock(status_code=404)
        resp_200 = MagicMock(status_code=200)
        mock_gh.get.side_effect = [resp_404, resp_200, resp_404]

        urls = [
            "https://github.com/org/gone1",
            "https://github.com/org/still-alive",
            "https://github.com/org/gone2",
        ]
        result = _verify_repos_removed(mock_gh, urls)

        assert result == [
            "https://github.com/org/gone1",
            "https://github.com/org/gone2",
        ]
        assert mock_gh.get.call_count == 3

    def test_empty_list_returns_empty(self):
        from decision_hub.domain.tracker_service import _verify_repos_removed

        mock_gh = MagicMock()
        assert _verify_repos_removed(mock_gh, []) == []
        mock_gh.get.assert_not_called()

    def test_invalid_url_is_skipped(self):
        from decision_hub.domain.tracker_service import _verify_repos_removed

        mock_gh = MagicMock()
        result = _verify_repos_removed(mock_gh, ["not-a-github-url"])
        assert result == []
        mock_gh.get.assert_not_called()


class TestResurrectRemovedSkills:
    """Unit tests for resurrect_removed_skills."""

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test")
    @patch("decision_hub.infra.github_client.GitHubClient")
    @patch("decision_hub.infra.database.reenable_trackers_for_urls", return_value=2)
    @patch("decision_hub.infra.database.clear_source_removed_for_urls", return_value=5)
    @patch("decision_hub.infra.database.fetch_removed_source_repo_urls")
    @patch("decision_hub.infra.database.create_engine")
    def test_resurrects_alive_repos(
        self,
        mock_engine,
        mock_fetch_removed,
        mock_clear_removed,
        mock_reenable,
        mock_gh_class,
        _mock_token,
    ):
        from decision_hub.domain.tracker_service import resurrect_removed_skills

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_fetch_removed.return_value = [
            "https://github.com/org/alive-repo",
            "https://github.com/org/gone-repo",
        ]

        # First call (alive-repo) returns 200, second (gone-repo) returns 404
        mock_gh_instance = MagicMock()
        resp_200 = MagicMock(status_code=200)
        resp_404 = MagicMock(status_code=404)
        mock_gh_instance.get.side_effect = [resp_200, resp_404]
        mock_gh_class.return_value.__enter__ = MagicMock(return_value=mock_gh_instance)
        mock_gh_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        result = resurrect_removed_skills(mock_settings)

        assert result["checked"] == 2
        assert result["resurrected"] == 1
        assert result["confirmed_removed"] == 1
        assert result["skills_resurrected"] == 5
        assert result["trackers_reenabled"] == 2

        mock_clear_removed.assert_called_once_with(mock_conn, ["https://github.com/org/alive-repo"])
        mock_reenable.assert_called_once_with(mock_conn, ["https://github.com/org/alive-repo"])

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test")
    @patch("decision_hub.infra.database.fetch_removed_source_repo_urls")
    @patch("decision_hub.infra.database.create_engine")
    def test_no_removed_skills_is_noop(
        self,
        mock_engine,
        mock_fetch_removed,
        _mock_token,
    ):
        from decision_hub.domain.tracker_service import resurrect_removed_skills

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_fetch_removed.return_value = []

        mock_settings = MagicMock()
        result = resurrect_removed_skills(mock_settings)

        assert result == {"checked": 0, "resurrected": 0, "confirmed_removed": 0}


class TestProcessTrackerNoSkillsDisables:
    """Verify process_tracker disables tracker when no skills found."""

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
        """When discover_skills returns empty, tracker should be disabled.
        The repo still exists on GitHub (it was successfully cloned), so
        source_repo_removed must NOT be set — that flag is reserved for
        repos that have been deleted/made private (GraphQL permanent error)."""
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

            # The repo still exists — do NOT mark skills as source_removed
            mock_mark.assert_not_called()


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
        mock_batch_fetch.return_value = ({"myorg/shared-repo:main": "same_sha"}, set(), {"myorg/shared-repo": 99}, {})

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
        total_disabled = 0
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
            total_disabled += result.trackers_disabled
            iterations += 1
            if result.checked == 0:
                break
            if result.skipped_rate_limit > 0:
                break
            if result.deadline_deferred > 0:
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
            "total_disabled": total_disabled,
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
                trackers_disabled=0,
                skipped_rate_limit=0,
                deadline_deferred=0,
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
                trackers_disabled=0,
                skipped_rate_limit=0,
                deadline_deferred=0,
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
                trackers_disabled=0,
                skipped_rate_limit=0,
                deadline_deferred=0,
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
                trackers_disabled=0,
                skipped_rate_limit=0,
                deadline_deferred=0,
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
                trackers_disabled=0,
                skipped_rate_limit=3,
                deadline_deferred=0,
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
                trackers_disabled=0,
                skipped_rate_limit=0,
                deadline_deferred=0,
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
                trackers_disabled=0,
                skipped_rate_limit=0,
                deadline_deferred=0,
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
                trackers_disabled=0,
                skipped_rate_limit=0,
                deadline_deferred=0,
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
                trackers_disabled=0,
                skipped_rate_limit=0,
                deadline_deferred=0,
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
            trackers_disabled=0,
            skipped_rate_limit=0,
            deadline_deferred=0,
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
            trackers_disabled=0,
            skipped_rate_limit=0,
            deadline_deferred=0,
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
            trackers_disabled=0,
            skipped_rate_limit=0,
            deadline_deferred=0,
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
            trackers_disabled=0,
            skipped_rate_limit=3,
            deadline_deferred=0,
            github_rate_remaining=100,
        )
        assert result.skipped_rate_limit == result.changed
        assert result.processed == 0
        assert result.checked == result.unchanged + result.changed + result.errored


class TestProcessTrackerMultiSkillPartialFailure:
    """Verify SHA handling when a multi-skill repo has partial failures (3/5 succeed, 2 fail)."""

    def _make_tracker(self) -> SkillTracker:
        return SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="myorg",
            repo_url="https://github.com/myorg/multi-skills",
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
    @patch("decision_hub.domain.tracker_service.has_new_commits", return_value=(True, "new_sha_multi"))
    @patch("decision_hub.domain.tracker_service.clone_repo")
    @patch("decision_hub.domain.tracker_service.discover_skills")
    @patch("decision_hub.infra.storage.create_s3_client")
    @patch("decision_hub.domain.tracker_service._publish_skill_from_tracker")
    def test_three_of_five_succeed_advances_sha_clears_error(
        self,
        mock_publish,
        _mock_s3,
        mock_discover,
        mock_clone,
        _mock_commits,
        _mock_token,
    ):
        """When 3 out of 5 skills succeed and 2 fail, SHA advances and last_error is cleared."""
        tracker = self._make_tracker()
        mock_clone.return_value = Path("/tmp/fake/repo")
        mock_discover.return_value = [
            Path("/tmp/fake/repo/skill-a"),
            Path("/tmp/fake/repo/skill-b"),
            Path("/tmp/fake/repo/skill-c"),
            Path("/tmp/fake/repo/skill-d"),
            Path("/tmp/fake/repo/skill-e"),
        ]
        # 3 succeed (return True), 2 fail with errors
        mock_publish.side_effect = [
            True,
            RuntimeError("gauntlet error on skill-b"),
            True,
            True,
            RuntimeError("S3 timeout on skill-e"),
        ]

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
            # SHA advances because at least one skill succeeded
            assert kwargs["last_commit_sha"] == "new_sha_multi"
            # last_error is None because not all failed
            assert kwargs["last_error"] is None
            # last_published_at should be set because 3 skills were published
            assert kwargs["last_published_at"] is not None

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test_token")
    @patch("decision_hub.domain.tracker_service.has_new_commits", return_value=(True, "new_sha_all_fail"))
    @patch("decision_hub.domain.tracker_service.clone_repo")
    @patch("decision_hub.domain.tracker_service.discover_skills")
    @patch("decision_hub.infra.storage.create_s3_client")
    @patch("decision_hub.domain.tracker_service._publish_skill_from_tracker")
    def test_all_five_fail_does_not_advance_sha_sets_error(
        self,
        mock_publish,
        _mock_s3,
        mock_discover,
        mock_clone,
        _mock_commits,
        _mock_token,
    ):
        """When all 5 skills fail, SHA does NOT advance and last_error captures all failures."""
        tracker = self._make_tracker()
        mock_clone.return_value = Path("/tmp/fake/repo")
        mock_discover.return_value = [
            Path("/tmp/fake/repo/skill-a"),
            Path("/tmp/fake/repo/skill-b"),
            Path("/tmp/fake/repo/skill-c"),
            Path("/tmp/fake/repo/skill-d"),
            Path("/tmp/fake/repo/skill-e"),
        ]
        mock_publish.side_effect = [
            RuntimeError("fail-a"),
            RuntimeError("fail-b"),
            RuntimeError("fail-c"),
            RuntimeError("fail-d"),
            RuntimeError("fail-e"),
        ]

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
            # SHA should NOT advance when all failed
            assert kwargs["last_commit_sha"] is None
            # Error should be recorded with all failure messages
            assert kwargs["last_error"] is not None
            assert "fail-a" in kwargs["last_error"]
            assert "fail-e" in kwargs["last_error"]
            # last_published_at should be None
            assert kwargs["last_published_at"] is None


class TestDetectRemovedSkills:
    """Verify _detect_removed_skills marks DB skills missing from repo discovery."""

    def _make_tracker(self) -> SkillTracker:
        return SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="myorg",
            repo_url="https://github.com/myorg/myrepo",
            branch="main",
            enabled=True,
            poll_interval_minutes=5,
            last_commit_sha="abc123",
            last_checked_at=None,
            last_published_at=None,
            last_error=None,
            created_at=datetime.now(UTC),
        )

    @patch("decision_hub.domain.tracker_service.parse_skill_md")
    @patch("decision_hub.infra.database.fetch_skill_names_by_source_repo")
    @patch("decision_hub.infra.database.mark_skills_removed_by_name")
    def test_missing_skills_are_marked_removed(
        self,
        mock_mark,
        mock_fetch,
        mock_parse,
    ):
        """Skills in DB but not in discovered dirs should be marked as removed."""
        from decision_hub.domain.tracker_service import _detect_removed_skills

        tracker = self._make_tracker()

        manifest_a = MagicMock()
        manifest_a.name = "skill-a"
        mock_parse.return_value = manifest_a

        skill_dirs = [Path("/tmp/fake/repo/skill-a")]

        # DB has skill-a and skill-b
        mock_fetch.return_value = {"skill-a", "skill-b"}
        mock_mark.return_value = 1

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        _detect_removed_skills(skill_dirs, tracker, mock_engine)

        mock_fetch.assert_called_once_with(mock_conn, "myorg", "https://github.com/myorg/myrepo")
        mock_mark.assert_called_once_with(mock_conn, "myorg", {"skill-b"})
        mock_conn.commit.assert_called_once()

    @patch("decision_hub.domain.tracker_service.parse_skill_md")
    @patch("decision_hub.infra.database.fetch_skill_names_by_source_repo")
    @patch("decision_hub.infra.database.mark_skills_removed_by_name")
    def test_no_removal_when_all_present(
        self,
        mock_mark,
        mock_fetch,
        mock_parse,
    ):
        """When all DB skills are still discovered, mark function should not be called."""
        from decision_hub.domain.tracker_service import _detect_removed_skills

        tracker = self._make_tracker()

        manifest_a = MagicMock()
        manifest_a.name = "skill-a"
        mock_parse.return_value = manifest_a

        skill_dirs = [Path("/tmp/fake/repo/skill-a")]
        mock_fetch.return_value = {"skill-a"}

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        _detect_removed_skills(skill_dirs, tracker, mock_engine)

        mock_fetch.assert_called_once()
        mock_mark.assert_not_called()
        mock_conn.commit.assert_not_called()

    @patch("decision_hub.domain.tracker_service.parse_skill_md")
    @patch("decision_hub.infra.database.fetch_skill_names_by_source_repo")
    @patch("decision_hub.infra.database.mark_skills_removed_by_name")
    def test_no_removal_when_no_db_skills(
        self,
        mock_mark,
        mock_fetch,
        mock_parse,
    ):
        """Fresh repo with no prior DB skills should not trigger any removal."""
        from decision_hub.domain.tracker_service import _detect_removed_skills

        tracker = self._make_tracker()

        manifest_a = MagicMock()
        manifest_a.name = "skill-a"
        mock_parse.return_value = manifest_a

        skill_dirs = [Path("/tmp/fake/repo/skill-a")]
        mock_fetch.return_value = set()

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        _detect_removed_skills(skill_dirs, tracker, mock_engine)

        mock_fetch.assert_called_once()
        mock_mark.assert_not_called()
        mock_conn.commit.assert_not_called()

    @patch("decision_hub.domain.tracker_service.parse_skill_md")
    @patch("decision_hub.infra.database.fetch_skill_names_by_source_repo")
    @patch("decision_hub.infra.database.mark_skills_removed_by_name")
    def test_all_parses_failed_skips_removal(
        self,
        mock_mark,
        mock_fetch,
        mock_parse,
    ):
        """When all SKILL.md parses fail, should not mark anything as removed."""
        from decision_hub.domain.tracker_service import _detect_removed_skills

        tracker = self._make_tracker()

        # Every parse raises ValueError
        mock_parse.side_effect = ValueError("bad manifest")

        skill_dirs = [Path("/tmp/fake/repo/skill-a"), Path("/tmp/fake/repo/skill-b")]

        mock_engine = MagicMock()

        _detect_removed_skills(skill_dirs, tracker, mock_engine)

        # Should bail out before even opening a DB connection
        mock_engine.connect.assert_not_called()
        mock_fetch.assert_not_called()
        mock_mark.assert_not_called()


class TestCircuitBreaker:
    """When >50% of trackers return permanent errors, treat all as transient."""

    def _make_tracker(self, repo_name: str) -> SkillTracker:
        return SkillTracker(
            id=uuid4(),
            user_id=uuid4(),
            org_slug="myorg",
            repo_url=f"https://github.com/myorg/{repo_name}",
            branch="main",
            enabled=True,
            poll_interval_minutes=60,
            last_commit_sha="old_sha",
            last_checked_at=None,
            last_published_at=None,
            last_error=None,
            created_at=datetime.now(UTC),
        )

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test")
    @patch("decision_hub.domain.tracker_service._dispatch_changed_trackers", return_value=(0, 0))
    @patch("decision_hub.infra.database.batch_defer_trackers")
    @patch("decision_hub.infra.database.batch_clear_tracker_errors")
    @patch("decision_hub.infra.database.batch_set_tracker_errors")
    @patch("decision_hub.infra.database.batch_update_github_stars")
    @patch("decision_hub.infra.database.batch_update_github_repo_metadata")
    @patch("decision_hub.infra.database.batch_increment_permanent_failures")
    @patch("decision_hub.infra.database.batch_disable_trackers")
    @patch("decision_hub.infra.database.mark_skills_source_removed")
    @patch("decision_hub.infra.github_client.batch_fetch_commit_shas")
    @patch("decision_hub.infra.github_client.GitHubClient")
    @patch("decision_hub.infra.database.claim_due_trackers")
    @patch("decision_hub.infra.database.create_engine")
    def test_circuit_breaker_downgrades_permanent_to_transient(
        self,
        mock_create_engine,
        mock_claim,
        mock_gh_class,
        mock_batch_fetch,
        mock_mark_removed,
        mock_batch_disable,
        mock_increment,
        mock_batch_meta,
        mock_batch_stars,
        mock_batch_set_errors,
        mock_batch_clear_errors,
        mock_batch_defer,
        mock_dispatch,
        _mock_token,
    ):
        """When 3 out of 4 trackers return permanent errors (>50%),
        circuit breaker should treat all as transient — no increment, no disable."""
        trackers = [self._make_tracker(f"repo-{i}") for i in range(4)]

        mock_conn = MagicMock()
        mock_create_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_create_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_claim.return_value = trackers

        # Only 1 tracker gets a SHA (unchanged), 3 return None (would be permanent)
        mock_batch_fetch.return_value = (
            {"myorg/repo-0:main": "old_sha"},  # repo-0 unchanged
            set(),  # no chunk failures
            {},
            {},
        )

        mock_gh_instance = MagicMock()
        mock_gh_instance.rate_limit_remaining = 5000
        mock_gh_class.return_value.__enter__ = MagicMock(return_value=mock_gh_instance)
        mock_gh_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.tracker_batch_size = 100
        mock_settings.tracker_jitter_seconds = 0
        mock_settings.tracker_rate_limit_floor = 500
        mock_settings.tracker_permanent_failure_threshold = 10
        mock_settings.tracker_circuit_breaker_ratio = 0.5

        check_all_due_trackers(mock_settings)

        # All 3 "permanent" errors should be downgraded to transient
        # So batch_increment_permanent_failures should NOT be called
        mock_increment.assert_not_called()
        mock_batch_disable.assert_not_called()
        mock_mark_removed.assert_not_called()

        # The 3 permanent errors were downgraded to transient, verify via batch_set_tracker_errors calls
        # There should be a call with the "circuit breaker" message for 3 trackers
        all_set_error_calls = mock_batch_set_errors.call_args_list
        circuit_breaker_calls = [c for c in all_set_error_calls if "circuit breaker" in str(c).lower()]
        assert len(circuit_breaker_calls) == 1
        # Should contain the 3 tracker IDs that were downgraded
        downgraded_ids = circuit_breaker_calls[0][0][1]
        assert len(downgraded_ids) == 3

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value="ghs_test")
    @patch("decision_hub.domain.tracker_service._dispatch_changed_trackers", return_value=(0, 0))
    @patch("decision_hub.infra.database.batch_defer_trackers")
    @patch("decision_hub.infra.database.batch_clear_tracker_errors")
    @patch("decision_hub.infra.database.batch_set_tracker_errors")
    @patch("decision_hub.infra.database.batch_update_github_stars")
    @patch("decision_hub.infra.database.batch_update_github_repo_metadata")
    @patch("decision_hub.infra.database.batch_increment_permanent_failures")
    @patch("decision_hub.infra.database.batch_disable_trackers")
    @patch("decision_hub.infra.database.mark_skills_source_removed")
    @patch("decision_hub.infra.github_client.batch_fetch_commit_shas")
    @patch("decision_hub.infra.github_client.GitHubClient")
    @patch("decision_hub.infra.database.claim_due_trackers")
    @patch("decision_hub.infra.database.create_engine")
    def test_circuit_breaker_does_not_trip_below_threshold(
        self,
        mock_create_engine,
        mock_claim,
        mock_gh_class,
        mock_batch_fetch,
        mock_mark_removed,
        mock_batch_disable,
        mock_increment,
        mock_batch_meta,
        mock_batch_stars,
        mock_batch_set_errors,
        mock_batch_clear_errors,
        mock_batch_defer,
        mock_dispatch,
        _mock_token,
    ):
        """When only 1 out of 4 trackers returns permanent error (25% < 50%),
        circuit breaker should NOT trip — permanent errors processed normally."""
        trackers = [self._make_tracker(f"repo-{i}") for i in range(4)]

        mock_conn = MagicMock()
        mock_create_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_create_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_claim.return_value = trackers

        # 3 trackers get SHAs (unchanged), 1 returns None (permanent)
        mock_batch_fetch.return_value = (
            {
                "myorg/repo-0:main": "old_sha",
                "myorg/repo-1:main": "old_sha",
                "myorg/repo-2:main": "old_sha",
            },
            set(),
            {},
            {},
        )

        mock_gh_instance = MagicMock()
        mock_gh_instance.rate_limit_remaining = 5000
        mock_gh_class.return_value.__enter__ = MagicMock(return_value=mock_gh_instance)
        mock_gh_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.tracker_batch_size = 100
        mock_settings.tracker_jitter_seconds = 0
        mock_settings.tracker_rate_limit_floor = 500
        mock_settings.tracker_permanent_failure_threshold = 10
        mock_settings.tracker_circuit_breaker_ratio = 0.5

        # batch_increment returns empty (no threshold crossed)
        mock_increment.return_value = []

        check_all_due_trackers(mock_settings)

        # Circuit breaker should NOT trip — only 25% permanent errors
        # batch_increment_permanent_failures SHOULD be called (normal path)
        mock_increment.assert_called_once()
        # The permanent error call should have 1 tracker ID
        perm_ids = mock_increment.call_args[0][1]
        assert len(perm_ids) == 1
