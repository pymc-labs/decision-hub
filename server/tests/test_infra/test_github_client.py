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
        client.graphql.return_value = {"r0": {"ref": {"target": {"oid": "abc123def456"}}}}

        result = batch_fetch_commit_shas(client, [("owner", "repo", "main")])

        assert result == {"owner/repo:main": "abc123def456"}
        client.graphql.assert_called_once()

    def test_missing_repo_omitted(self):
        client = MagicMock(spec=GitHubClient)
        client.graphql.return_value = {"r0": None, "r1": {"ref": {"target": {"oid": "sha456"}}}}

        result = batch_fetch_commit_shas(
            client,
            [("owner", "missing", "main"), ("owner", "repo", "main")],
        )

        assert result == {"owner/repo:main": "sha456"}

    def test_empty_ref_omitted(self):
        """Repos with no ref (empty repo, bad branch) are skipped."""
        client = MagicMock(spec=GitHubClient)
        client.graphql.return_value = {"r0": {"ref": None}}

        result = batch_fetch_commit_shas(client, [("owner", "empty", "main")])
        assert result == {}

    def test_graphql_failure_skips_chunk(self):
        """When GraphQL raises, that chunk is skipped rather than failing."""
        client = MagicMock(spec=GitHubClient)
        client.graphql.side_effect = httpx.HTTPStatusError("forbidden", request=MagicMock(), response=MagicMock())

        result = batch_fetch_commit_shas(client, [("owner", "repo", "main")])
        assert result == {}

    def test_multiple_repos(self):
        client = MagicMock(spec=GitHubClient)
        client.graphql.return_value = {
            "r0": {"ref": {"target": {"oid": "sha1"}}},
            "r1": {"ref": {"target": {"oid": "sha2"}}},
            "r2": {"ref": {"target": {"oid": "sha3"}}},
        }

        repos = [
            ("org", "repo-a", "main"),
            ("org", "repo-b", "develop"),
            ("other", "repo-c", "main"),
        ]
        result = batch_fetch_commit_shas(client, repos)

        assert result == {
            "org/repo-a:main": "sha1",
            "org/repo-b:develop": "sha2",
            "other/repo-c:main": "sha3",
        }

    def test_same_repo_different_branches(self):
        """Two trackers on different branches of the same repo get distinct keys."""
        client = MagicMock(spec=GitHubClient)
        client.graphql.return_value = {
            "r0": {"ref": {"target": {"oid": "sha_main"}}},
            "r1": {"ref": {"target": {"oid": "sha_dev"}}},
        }

        repos = [
            ("org", "repo", "main"),
            ("org", "repo", "develop"),
        ]
        result = batch_fetch_commit_shas(client, repos)

        assert result == {
            "org/repo:main": "sha_main",
            "org/repo:develop": "sha_dev",
        }
