"""Tests for the tracker domain logic (URL parsing, commit checking)."""

import pytest
import respx
import httpx

from decision_hub.domain.tracker import (
    fetch_latest_commit_sha,
    has_new_commits,
    parse_github_repo_url,
)


class TestParseGithubRepoUrl:
    """URL parsing for GitHub repos."""

    def test_https_url(self) -> None:
        """Parses standard HTTPS GitHub URL."""
        owner, repo = parse_github_repo_url("https://github.com/pymc-labs/decision-hub")
        assert owner == "pymc-labs"
        assert repo == "decision-hub"

    def test_https_url_with_git_suffix(self) -> None:
        """Parses HTTPS URL ending in .git."""
        owner, repo = parse_github_repo_url("https://github.com/org/repo.git")
        assert owner == "org"
        assert repo == "repo"

    def test_https_url_with_trailing_slash(self) -> None:
        """Parses HTTPS URL with trailing slash."""
        owner, repo = parse_github_repo_url("https://github.com/org/repo/")
        assert owner == "org"
        assert repo == "repo"

    def test_ssh_url(self) -> None:
        """Parses SSH-style GitHub URL."""
        owner, repo = parse_github_repo_url("git@github.com:org/repo.git")
        assert owner == "org"
        assert repo == "repo"

    def test_ssh_url_without_git_suffix(self) -> None:
        """Parses SSH-style URL without .git extension."""
        owner, repo = parse_github_repo_url("git@github.com:org/repo")
        assert owner == "org"
        assert repo == "repo"

    def test_non_github_url_raises(self) -> None:
        """Rejects non-GitHub URLs."""
        with pytest.raises(ValueError, match="Not a GitHub repo URL"):
            parse_github_repo_url("https://gitlab.com/org/repo")

    def test_invalid_url_raises(self) -> None:
        """Rejects malformed URLs."""
        with pytest.raises(ValueError, match="Not a GitHub repo URL"):
            parse_github_repo_url("not-a-url")

    def test_http_url(self) -> None:
        """Parses HTTP (non-HTTPS) GitHub URL."""
        owner, repo = parse_github_repo_url("http://github.com/owner/repo")
        assert owner == "owner"
        assert repo == "repo"


class TestFetchLatestCommitSha:
    """GitHub API calls for commit SHA."""

    @respx.mock
    def test_fetches_sha_from_github_api(self) -> None:
        """Returns SHA from successful API response."""
        route = respx.get("https://api.github.com/repos/org/repo/commits/main").mock(
            return_value=httpx.Response(200, json={"sha": "abc123def456"})
        )

        sha = fetch_latest_commit_sha("org", "repo", "main")
        assert sha == "abc123def456"
        assert route.called

    @respx.mock
    def test_sends_auth_header_when_token_provided(self) -> None:
        """Includes authorization header when a GitHub token is passed."""
        route = respx.get("https://api.github.com/repos/org/repo/commits/main").mock(
            return_value=httpx.Response(200, json={"sha": "abc123"})
        )

        fetch_latest_commit_sha("org", "repo", "main", github_token="ghp_test")
        request = route.calls[0].request
        assert request.headers["Authorization"] == "token ghp_test"

    @respx.mock
    def test_raises_on_404(self) -> None:
        """Raises on missing repo/branch."""
        respx.get("https://api.github.com/repos/org/repo/commits/main").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )

        with pytest.raises(httpx.HTTPStatusError):
            fetch_latest_commit_sha("org", "repo", "main")

    @respx.mock
    def test_custom_branch(self) -> None:
        """Passes the branch name to the API URL."""
        route = respx.get("https://api.github.com/repos/org/repo/commits/develop").mock(
            return_value=httpx.Response(200, json={"sha": "dev123"})
        )

        sha = fetch_latest_commit_sha("org", "repo", "develop")
        assert sha == "dev123"
        assert route.called


class TestHasNewCommits:
    """SHA comparison logic."""

    @respx.mock
    def test_detects_new_commits(self) -> None:
        """Returns changed=True when SHA differs from last known."""
        respx.get("https://api.github.com/repos/org/repo/commits/main").mock(
            return_value=httpx.Response(200, json={"sha": "new_sha"})
        )

        changed, current = has_new_commits("org", "repo", "main", "old_sha")
        assert changed is True
        assert current == "new_sha"

    @respx.mock
    def test_no_change_when_sha_matches(self) -> None:
        """Returns changed=False when SHA matches last known."""
        respx.get("https://api.github.com/repos/org/repo/commits/main").mock(
            return_value=httpx.Response(200, json={"sha": "same_sha"})
        )

        changed, current = has_new_commits("org", "repo", "main", "same_sha")
        assert changed is False
        assert current == "same_sha"

    @respx.mock
    def test_first_check_always_returns_changed(self) -> None:
        """Returns changed=True on first check (last_known_sha is None)."""
        respx.get("https://api.github.com/repos/org/repo/commits/main").mock(
            return_value=httpx.Response(200, json={"sha": "first_sha"})
        )

        changed, current = has_new_commits("org", "repo", "main", None)
        assert changed is True
        assert current == "first_sha"
