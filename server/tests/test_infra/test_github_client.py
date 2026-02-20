"""Tests for decision_hub.infra.github_client."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from decision_hub.infra.github_client import GitHubClient, batch_fetch_commit_shas


class TestGitHubClientRateLimit:
    """Verify rate-limit state tracking."""

    def test_initial_rate_limit(self):
        with GitHubClient() as gh:
            assert gh._rate_limit_remaining == 999

    def test_update_rate_limit_from_headers(self):
        with GitHubClient() as gh:
            resp = MagicMock()
            resp.headers = {
                "x-ratelimit-remaining": "42",
                "x-ratelimit-reset": "1700000000.0",
            }
            gh._update_rate_limit(resp)
            assert gh._rate_limit_remaining == 42
            assert gh._rate_limit_reset == 1700000000.0

    def test_update_rate_limit_missing_headers(self):
        with GitHubClient() as gh:
            resp = MagicMock()
            resp.headers = {}
            gh._update_rate_limit(resp)
            # Should keep defaults
            assert gh._rate_limit_remaining == 999


class TestGitHubClientRateLimitProperty:
    """Verify the public rate_limit_remaining property."""

    def test_initial_value(self):
        with GitHubClient() as gh:
            assert gh.rate_limit_remaining == 999

    def test_reflects_updated_value(self):
        with GitHubClient() as gh:
            resp = MagicMock()
            resp.headers = {"x-ratelimit-remaining": "42", "x-ratelimit-reset": "1700000000.0"}
            gh._update_rate_limit(resp)
            assert gh.rate_limit_remaining == 42


class TestGitHubClientContextManager:
    """Verify context manager protocol."""

    def test_enter_returns_self(self):
        gh = GitHubClient()
        result = gh.__enter__()
        assert result is gh
        gh.close()

    def test_exit_closes_client(self):
        gh = GitHubClient()
        gh._client = MagicMock()
        gh.__exit__(None, None, None)
        gh._client.close.assert_called_once()


class TestGitHubClientGraphQL:
    """Verify GraphQL method."""

    @patch("decision_hub.infra.github_client.httpx.post")
    def test_graphql_success(self, mock_post):
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "1700000000"}
        resp.json.return_value = {"data": {"viewer": {"login": "test"}}}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        with GitHubClient(token="ghp_test") as gh:
            result = gh.graphql("{ viewer { login } }")

        assert result == {"viewer": {"login": "test"}}

    @patch("decision_hub.infra.github_client.httpx.post")
    def test_graphql_errors_without_data_raises(self, mock_post):
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.json.return_value = {"errors": [{"message": "bad query"}]}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        with GitHubClient() as gh, pytest.raises(ValueError, match="GraphQL errors"):
            gh.graphql("{ bad }")

    @patch("decision_hub.infra.github_client.httpx.post")
    def test_graphql_partial_errors_returns_data(self, mock_post):
        """When both data and errors are present, return data instead of raising."""
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.json.return_value = {
            "data": {"r0": {"ref": {"target": {"oid": "abc123"}}}},
            "errors": [{"message": "Could not resolve to a Repository"}],
        }
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        with GitHubClient(token="ghp_test") as gh:
            result = gh.graphql("query { ... }")

        assert result == {"r0": {"ref": {"target": {"oid": "abc123"}}}}


class TestBatchFetchCommitShas:
    """Verify batch GraphQL commit SHA fetching."""

    def test_single_repo(self):
        client = MagicMock(spec=GitHubClient)
        client.graphql.return_value = {"r0": {"stargazerCount": 42, "ref": {"target": {"oid": "abc123def456"}}}}

        sha_map, failed_keys, stars = batch_fetch_commit_shas(client, [("owner", "repo", "main")])

        assert sha_map == {"owner/repo:main": "abc123def456"}
        assert failed_keys == set()
        assert stars == {"owner/repo": 42}
        client.graphql.assert_called_once()

    def test_missing_repo_omitted(self):
        client = MagicMock(spec=GitHubClient)
        client.graphql.return_value = {"r0": None, "r1": {"stargazerCount": 10, "ref": {"target": {"oid": "sha456"}}}}

        sha_map, failed_keys, stars = batch_fetch_commit_shas(
            client,
            [("owner", "missing", "main"), ("owner", "repo", "main")],
        )

        assert sha_map == {"owner/repo:main": "sha456"}
        assert failed_keys == set()
        assert stars == {"owner/repo": 10}

    def test_empty_ref_omitted(self):
        """Repos with no ref (empty repo, bad branch) are skipped."""
        client = MagicMock(spec=GitHubClient)
        client.graphql.return_value = {"r0": {"stargazerCount": 5, "ref": None}}

        sha_map, failed_keys, stars = batch_fetch_commit_shas(client, [("owner", "empty", "main")])
        assert sha_map == {}
        assert failed_keys == set()
        # Stars should still be captured even when ref is missing
        assert stars == {"owner/empty": 5}

    def test_graphql_failure_skips_chunk(self):
        """When GraphQL raises, that chunk is skipped and keys go to failed_keys."""
        client = MagicMock(spec=GitHubClient)
        client.graphql.side_effect = httpx.HTTPStatusError("forbidden", request=MagicMock(), response=MagicMock())

        sha_map, failed_keys, stars = batch_fetch_commit_shas(client, [("owner", "repo", "main")])
        assert sha_map == {}
        assert failed_keys == {"owner/repo:main"}
        assert stars == {}

    def test_network_error_skips_chunk(self):
        """Transient network errors (ConnectError, Timeout) are caught per-chunk."""
        client = MagicMock(spec=GitHubClient)
        client.graphql.side_effect = httpx.ConnectError("connection refused")

        sha_map, failed_keys, stars = batch_fetch_commit_shas(client, [("owner", "repo", "main")])
        assert sha_map == {}
        assert failed_keys == {"owner/repo:main"}
        assert stars == {}

    def test_multiple_repos(self):
        client = MagicMock(spec=GitHubClient)
        client.graphql.return_value = {
            "r0": {"stargazerCount": 100, "ref": {"target": {"oid": "sha1"}}},
            "r1": {"stargazerCount": 200, "ref": {"target": {"oid": "sha2"}}},
            "r2": {"stargazerCount": 50, "ref": {"target": {"oid": "sha3"}}},
        }

        repos = [
            ("org", "repo-a", "main"),
            ("org", "repo-b", "develop"),
            ("other", "repo-c", "main"),
        ]
        sha_map, failed_keys, stars = batch_fetch_commit_shas(client, repos)

        assert sha_map == {
            "org/repo-a:main": "sha1",
            "org/repo-b:develop": "sha2",
            "other/repo-c:main": "sha3",
        }
        assert failed_keys == set()
        assert stars == {"org/repo-a": 100, "org/repo-b": 200, "other/repo-c": 50}

    def test_same_repo_different_branches(self):
        """Two trackers on different branches of the same repo get distinct keys."""
        client = MagicMock(spec=GitHubClient)
        client.graphql.return_value = {
            "r0": {"stargazerCount": 77, "ref": {"target": {"oid": "sha_main"}}},
            "r1": {"stargazerCount": 77, "ref": {"target": {"oid": "sha_dev"}}},
        }

        repos = [
            ("org", "repo", "main"),
            ("org", "repo", "develop"),
        ]
        sha_map, failed_keys, stars = batch_fetch_commit_shas(client, repos)

        assert sha_map == {
            "org/repo:main": "sha_main",
            "org/repo:develop": "sha_dev",
        }
        assert failed_keys == set()
        # Same repo, both branches report same star count — deduplicated by owner/repo key
        assert stars == {"org/repo": 77}

    def test_unsafe_branch_name_skipped(self):
        """Branch names with injection characters are silently skipped."""
        client = MagicMock(spec=GitHubClient)
        client.graphql.return_value = {
            "r0": {"stargazerCount": 10, "ref": {"target": {"oid": "sha_safe"}}},
        }

        repos = [
            ("org", "repo", "main"),
            ("org", "repo", 'feat") { ref(qualifiedName: "refs/heads/main'),
        ]
        sha_map, failed_keys, stars = batch_fetch_commit_shas(client, repos)

        # Only the safe repo should appear; the malicious branch is skipped
        assert sha_map == {"org/repo:main": "sha_safe"}
        assert failed_keys == set()
        assert stars == {"org/repo": 10}
        # GraphQL should still be called (with just 1 alias for the safe repo)
        client.graphql.assert_called_once()


class TestBatchFetchTransientFailures:
    """Verify transient failure tracking across chunks."""

    def test_first_chunk_fails_second_succeeds(self):
        """When the first chunk fails, its keys are in failed_keys; second chunk succeeds."""
        client = MagicMock(spec=GitHubClient)

        # Build 251 repos: first 250 in chunk 0, last 1 in chunk 1
        repos = [(f"org{i}", f"repo{i}", "main") for i in range(251)]

        # First call (chunk 0) fails, second call (chunk 1) succeeds
        client.graphql.side_effect = [
            httpx.ConnectError("timeout"),
            {"r0": {"stargazerCount": 1, "ref": {"target": {"oid": "sha_last"}}}},
        ]

        sha_map, failed_keys, stars = batch_fetch_commit_shas(client, repos)

        # Last repo succeeds
        assert sha_map == {"org250/repo250:main": "sha_last"}
        assert stars == {"org250/repo250": 1}
        # First 250 repos are in failed_keys
        assert len(failed_keys) == 250
        assert "org0/repo0:main" in failed_keys
        assert "org249/repo249:main" in failed_keys
        # Last repo is NOT in failed_keys
        assert "org250/repo250:main" not in failed_keys

    def test_missing_repo_not_in_failed_keys(self):
        """A repo that returns null data (not found) is NOT in failed_keys."""
        client = MagicMock(spec=GitHubClient)
        client.graphql.return_value = {
            "r0": None,  # repo not found — null data
            "r1": {"stargazerCount": 5, "ref": {"target": {"oid": "sha_ok"}}},
        }

        repos = [("org", "missing", "main"), ("org", "found", "main")]
        sha_map, failed_keys, stars = batch_fetch_commit_shas(client, repos)

        assert sha_map == {"org/found:main": "sha_ok"}
        assert stars == {"org/found": 5}
        # missing repo is NOT in failed_keys — it's distinguishable from transient
        assert failed_keys == set()
