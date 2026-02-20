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


class TestProcessTrackerKnownSha:
    """Verify process_tracker skips REST check when known_sha is provided."""

    @patch("decision_hub.domain.tracker_service._resolve_github_token", return_value=None)
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

        check_all_due_trackers(mock_settings)

        mock_claim.assert_called_once_with(mock_conn, batch_size=42, jitter_seconds=120)


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

        processed, failed = _dispatch_changed_trackers(changed, None, mock_settings, mock_engine)

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

        processed, failed = _dispatch_changed_trackers(changed, None, mock_settings, mock_engine)

        assert processed == 0
        assert failed == 1


class TestCheckAllDueTrackersLoopSignal:
    """Verify check_all_due_trackers returns len(trackers) so the caller loop continues."""

    @patch("decision_hub.domain.tracker_service._dispatch_changed_trackers", return_value=(0, 0))
    @patch("decision_hub.infra.database.update_skill_tracker")
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
        mock_update_tracker,
        mock_dispatch,
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
        mock_batch_fetch.return_value = {f"myorg/repo-{i}:main": f"same_sha_{i}" for i in range(5)}

        mock_gh_instance = MagicMock()
        mock_gh_instance.rate_limit_remaining = 4000
        mock_gh_class.return_value.__enter__ = MagicMock(return_value=mock_gh_instance)
        mock_gh_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.tracker_batch_size = 100
        mock_settings.tracker_jitter_seconds = 0
        mock_settings.tracker_rate_limit_floor = 500
        mock_settings.github_token = "ghp_test"

        result = check_all_due_trackers(mock_settings)

        # Must return 5 (number of trackers claimed) so the loop continues
        assert result == 5
        # _dispatch_changed_trackers should be called with an empty list
        mock_dispatch.assert_called_once()
        changed_arg = mock_dispatch.call_args[0][0]
        assert len(changed_arg) == 0


class TestRateLimitGuardrail:
    """Verify check_all_due_trackers skips processing when GitHub rate limit is low."""

    @patch("decision_hub.domain.tracker_service._dispatch_changed_trackers")
    @patch("decision_hub.infra.database.update_skill_tracker")
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
        mock_update_tracker,
        mock_dispatch,
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
        mock_batch_fetch.return_value = {"myorg/myrepo:main": "new_sha"}

        # Set rate limit below floor
        mock_gh_instance = MagicMock()
        mock_gh_instance.rate_limit_remaining = 100
        mock_gh_class.return_value.__enter__ = MagicMock(return_value=mock_gh_instance)
        mock_gh_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.tracker_batch_size = 100
        mock_settings.tracker_jitter_seconds = 0
        mock_settings.tracker_rate_limit_floor = 500
        mock_settings.github_token = "ghp_test"

        result = check_all_due_trackers(mock_settings)

        # Should return 0 processed and NOT call _dispatch_changed_trackers
        assert result == 0
        mock_dispatch.assert_not_called()

        # Rate-limited trackers should be marked with error and cleared for next tick
        mock_update_tracker.assert_any_call(
            mock_conn,
            tracker.id,
            last_error="rate_limit: deferred to next tick",
            next_check_at=None,
        )

    @patch("decision_hub.domain.tracker_service._dispatch_changed_trackers", return_value=(1, 0))
    @patch("decision_hub.infra.database.update_skill_tracker")
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
        mock_update_tracker,
        mock_dispatch,
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
        mock_batch_fetch.return_value = {"myorg/myrepo:main": "new_sha"}

        # Set rate limit above floor
        mock_gh_instance = MagicMock()
        mock_gh_instance.rate_limit_remaining = 4000
        mock_gh_class.return_value.__enter__ = MagicMock(return_value=mock_gh_instance)
        mock_gh_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_settings = MagicMock()
        mock_settings.tracker_batch_size = 100
        mock_settings.tracker_jitter_seconds = 0
        mock_settings.tracker_rate_limit_floor = 500
        mock_settings.github_token = "ghp_test"

        result = check_all_due_trackers(mock_settings)

        assert result == 1
        mock_dispatch.assert_called_once()
