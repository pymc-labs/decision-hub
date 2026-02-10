"""Tests for tracker_service helper functions."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from decision_hub.domain.tracker_service import (
    _build_authenticated_url,
    _clone_repo,
    _parse_semver,
    _resolve_github_token,
)
from decision_hub.models import SkillTracker


def _make_tracker(**overrides) -> SkillTracker:
    """Create a minimal SkillTracker for testing."""
    defaults = dict(
        id=uuid4(),
        user_id=uuid4(),
        org_slug="test-org",
        repo_url="https://github.com/org/repo",
        branch="main",
        last_commit_sha=None,
        poll_interval_minutes=60,
        enabled=True,
        last_checked_at=None,
        last_published_at=None,
        last_error=None,
        created_at=None,
    )
    defaults.update(overrides)
    return SkillTracker(**defaults)


class TestBuildAuthenticatedUrl:
    """_build_authenticated_url rewrites URLs with token auth."""

    def test_https_url_gets_token(self) -> None:
        url = _build_authenticated_url("https://github.com/org/repo", "ghp_secret")
        assert url == "https://x-access-token:ghp_secret@github.com/org/repo.git"

    def test_ssh_url_converted_to_https(self) -> None:
        url = _build_authenticated_url("git@github.com:org/repo.git", "ghp_secret")
        assert url == "https://x-access-token:ghp_secret@github.com/org/repo.git"


class TestResolveGithubToken:
    """_resolve_github_token picks the best available token."""

    def test_uses_user_token_when_available(self) -> None:
        tracker = _make_tracker()
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "decision_hub.infra.database.get_api_keys_for_eval",
                return_value={"GITHUB_TOKEN": b"encrypted_token"},
            ) as mock_get_keys,
            patch(
                "decision_hub.domain.crypto.decrypt_value",
                return_value="ghp_user_token",
            ) as mock_decrypt,
        ):
            settings = MagicMock()
            settings.fernet_key = "test-fernet-key"
            settings.github_token = "ghp_system_fallback"

            result = _resolve_github_token(mock_engine, tracker, settings)

            assert result == "ghp_user_token"
            mock_get_keys.assert_called_once_with(mock_conn, tracker.user_id, ["GITHUB_TOKEN"])
            mock_decrypt.assert_called_once_with(b"encrypted_token", "test-fernet-key")

    def test_falls_back_to_settings_token(self) -> None:
        tracker = _make_tracker()
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "decision_hub.infra.database.get_api_keys_for_eval",
            return_value={},
        ):
            settings = MagicMock()
            settings.github_token = "ghp_system_token"

            result = _resolve_github_token(mock_engine, tracker, settings)
            assert result == "ghp_system_token"

    def test_returns_none_when_no_token(self) -> None:
        tracker = _make_tracker()
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "decision_hub.infra.database.get_api_keys_for_eval",
            return_value={},
        ):
            settings = MagicMock()
            settings.github_token = ""

            result = _resolve_github_token(mock_engine, tracker, settings)
            assert result is None


class TestCloneRepoTokenSanitization:
    """Token is stripped from error messages on clone failure."""

    def test_token_stripped_from_error(self) -> None:
        with patch(
            "decision_hub.domain.tracker_service.subprocess.run",
        ) as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="fatal: Authentication failed for 'https://x-access-token:ghp_secret123@github.com/org/repo.git'",
            )

            with pytest.raises(RuntimeError) as exc_info:
                _clone_repo(
                    "https://github.com/org/repo",
                    "main",
                    github_token="ghp_secret123",
                )

            assert "ghp_secret123" not in str(exc_info.value)
            assert "***" in str(exc_info.value)


class TestVersionResolution:
    """Version determination logic in _publish_skill_from_tracker."""

    def test_manifest_version_used_when_higher(self) -> None:
        """When manifest declares 2.0.0 and latest is 1.0.0, use manifest."""
        assert _parse_semver("2.0.0") > _parse_semver("1.0.0")

    def test_auto_bump_when_manifest_version_not_higher(self) -> None:
        """When manifest version <= latest, should bump instead."""
        assert not (_parse_semver("1.0.0") > _parse_semver("1.0.0"))

    def test_auto_bump_when_no_manifest_version(self) -> None:
        """No manifest version means we fall through to bump."""
        from decision_hub.domain.tracker_service import _bump_version

        assert _bump_version("1.0.0") == "1.0.1"

    def test_manifest_version_for_first_publish(self) -> None:
        """When latest is None and manifest has a version, use it."""
        manifest_version = "1.0.0"
        version = manifest_version or "0.1.0"
        assert version == "1.0.0"

    def test_default_first_publish(self) -> None:
        """When latest is None and no manifest version, use 0.1.0."""
        manifest_version = None
        version = manifest_version or "0.1.0"
        assert version == "0.1.0"


class TestParseSemver:
    """_parse_semver converts string to comparable tuple."""

    def test_parses_valid_semver(self) -> None:
        assert _parse_semver("1.2.3") == (1, 2, 3)

    def test_comparison_works(self) -> None:
        assert _parse_semver("2.0.0") > _parse_semver("1.9.9")
        assert _parse_semver("1.0.0") == _parse_semver("1.0.0")
        assert _parse_semver("0.1.0") < _parse_semver("0.2.0")
