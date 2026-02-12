"""Unit tests for GitHub URL parsing and commit SHA checking."""

from unittest.mock import patch

import pytest

from decision_hub.domain.tracker import (
    check_repo_accessible,
    has_new_commits,
    parse_github_repo_url,
)


class TestParseGithubRepoUrl:
    def test_parse_github_https_url(self):
        owner, repo = parse_github_repo_url("https://github.com/pymc-labs/decision-hub")
        assert owner == "pymc-labs"
        assert repo == "decision-hub"

    def test_parse_github_https_url_with_git_suffix(self):
        owner, repo = parse_github_repo_url("https://github.com/pymc-labs/decision-hub.git")
        assert owner == "pymc-labs"
        assert repo == "decision-hub"

    def test_parse_github_https_url_with_trailing_slash(self):
        owner, repo = parse_github_repo_url("https://github.com/pymc-labs/decision-hub/")
        assert owner == "pymc-labs"
        assert repo == "decision-hub"

    def test_parse_github_ssh_url(self):
        owner, repo = parse_github_repo_url("git@github.com:pymc-labs/decision-hub.git")
        assert owner == "pymc-labs"
        assert repo == "decision-hub"

    def test_parse_github_ssh_url_without_git_suffix(self):
        owner, repo = parse_github_repo_url("git@github.com:pymc-labs/decision-hub")
        assert owner == "pymc-labs"
        assert repo == "decision-hub"

    def test_parse_invalid_url_raises_value_error(self):
        with pytest.raises(ValueError, match="Not a GitHub repo URL"):
            parse_github_repo_url("https://gitlab.com/user/repo")

    def test_parse_non_url_raises_value_error(self):
        with pytest.raises(ValueError, match="Not a GitHub repo URL"):
            parse_github_repo_url("not-a-url")

    def test_parse_repo_with_dots_https(self):
        owner, repo = parse_github_repo_url("https://github.com/socketio/socket.io")
        assert owner == "socketio"
        assert repo == "socket.io"

    def test_parse_repo_with_dots_https_git_suffix(self):
        owner, repo = parse_github_repo_url("https://github.com/vuejs/vue.js.git")
        assert owner == "vuejs"
        assert repo == "vue.js"

    def test_parse_repo_with_dots_ssh(self):
        owner, repo = parse_github_repo_url("git@github.com:socketio/socket.io.git")
        assert owner == "socketio"
        assert repo == "socket.io"


class TestCheckRepoAccessible:
    @patch("decision_hub.domain.tracker.httpx.Client")
    def test_public_repo_returns_true(self, mock_client_cls):
        mock_resp = mock_client_cls.return_value.__enter__.return_value.get.return_value
        mock_resp.status_code = 200
        assert check_repo_accessible("owner", "repo") is True

    @patch("decision_hub.domain.tracker.httpx.Client")
    def test_private_repo_returns_false(self, mock_client_cls):
        mock_resp = mock_client_cls.return_value.__enter__.return_value.get.return_value
        mock_resp.status_code = 404
        assert check_repo_accessible("owner", "private-repo") is False

    @patch("decision_hub.domain.tracker.httpx.Client")
    def test_network_error_returns_false(self, mock_client_cls):
        import httpx

        mock_client_cls.return_value.__enter__.return_value.get.side_effect = httpx.ConnectError("timeout")
        assert check_repo_accessible("owner", "repo") is False


class TestHasNewCommits:
    @patch("decision_hub.domain.tracker.fetch_latest_commit_sha")
    def test_first_check_always_returns_true(self, mock_fetch):
        mock_fetch.return_value = "abc123"
        changed, sha = has_new_commits("owner", "repo", "main", None)
        assert changed is True
        assert sha == "abc123"

    @patch("decision_hub.domain.tracker.fetch_latest_commit_sha")
    def test_changed_sha_returns_true(self, mock_fetch):
        mock_fetch.return_value = "new-sha"
        changed, sha = has_new_commits("owner", "repo", "main", "old-sha")
        assert changed is True
        assert sha == "new-sha"

    @patch("decision_hub.domain.tracker.fetch_latest_commit_sha")
    def test_unchanged_sha_returns_false(self, mock_fetch):
        mock_fetch.return_value = "same-sha"
        changed, sha = has_new_commits("owner", "repo", "main", "same-sha")
        assert changed is False
        assert sha == "same-sha"
