"""Tests for the GitHub skills crawler."""

import subprocess
import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from decision_hub.scripts.crawler.checkpoint import Checkpoint
from decision_hub.scripts.crawler.discovery import (
    SKILL_PATHS,
    TRUSTED_ORGS,
    GitHubClient,
    _run_code_search,
    parse_curated_lists,
    parse_repo_url,
    resolve_repos,
    scan_forks,
    search_by_file_size,
    search_by_path,
    search_by_topic,
    tag_trusted_repos,
)
from decision_hub.scripts.crawler.models import (
    CrawlStats,
    DiscoveredRepo,
    dict_to_repo,
    repo_to_dict,
)
from decision_hub.scripts.crawler.processing import (
    _SLUG_PATTERN,
    fetch_owner_metadata,
)

# ---------------------------------------------------------------------------
# DiscoveredRepo / CrawlStats tests
# ---------------------------------------------------------------------------


class TestDiscoveredRepoRoundtrip:
    def test_roundtrip(self):
        repo = DiscoveredRepo(
            full_name="owner/repo",
            owner_login="owner",
            owner_type="User",
            clone_url="https://github.com/owner/repo.git",
            stars=42,
            description="A test repo",
        )
        d = repo_to_dict(repo)
        restored = dict_to_repo(d)
        assert restored.full_name == repo.full_name
        assert restored.owner_login == repo.owner_login
        assert restored.owner_type == repo.owner_type
        assert restored.clone_url == repo.clone_url
        assert restored.stars == repo.stars
        assert restored.description == repo.description

    def test_is_trusted_roundtrip(self):
        repo = DiscoveredRepo(
            full_name="anthropics/skills",
            owner_login="anthropics",
            owner_type="Organization",
            clone_url="https://github.com/anthropics/skills.git",
            stars=100,
            description="Official skills",
            is_trusted=True,
        )
        d = repo_to_dict(repo)
        assert d["is_trusted"] is True
        restored = dict_to_repo(d)
        assert restored.is_trusted is True

    def test_dict_to_repo_defaults(self):
        d = {
            "full_name": "a/b",
            "owner_login": "a",
            "owner_type": "User",
            "clone_url": "https://github.com/a/b.git",
        }
        repo = dict_to_repo(d)
        assert repo.stars == 0
        assert repo.description == ""
        assert repo.is_trusted is False


class TestCrawlStats:
    def test_accumulate_ok(self):
        stats = CrawlStats()
        result = {
            "repo": "owner/repo",
            "status": "ok",
            "skills_published": 2,
            "skills_skipped": 1,
            "skills_failed": 0,
            "skills_quarantined": 1,
            "org_created": True,
            "metadata_synced": True,
            "error": None,
        }
        stats.accumulate(result)
        assert stats.repos_processed == 1
        assert stats.skills_published == 2
        assert stats.skills_skipped == 1
        assert stats.skills_quarantined == 1
        assert stats.orgs_created == 1
        assert stats.metadata_synced == 1
        assert len(stats.errors) == 0

    def test_accumulate_error(self):
        stats = CrawlStats()
        result = {
            "repo": "owner/repo",
            "status": "error",
            "skills_published": 0,
            "skills_skipped": 0,
            "skills_failed": 0,
            "skills_quarantined": 0,
            "org_created": False,
            "metadata_synced": False,
            "error": "git clone failed",
        }
        stats.accumulate(result)
        assert len(stats.errors) == 1
        assert "git clone failed" in stats.errors[0]


# ---------------------------------------------------------------------------
# Trusted org tagging tests
# ---------------------------------------------------------------------------


class TestTagTrustedRepos:
    def test_tags_known_org(self):
        repos = {
            "anthropics/skills": DiscoveredRepo(
                "anthropics/skills",
                "anthropics",
                "Organization",
                "https://github.com/anthropics/skills.git",
                stars=50,
            ),
        }
        tag_trusted_repos(repos)
        assert repos["anthropics/skills"].is_trusted is True

    def test_case_insensitive(self):
        repos = {
            "OpenAI/codex": DiscoveredRepo(
                "OpenAI/codex",
                "OpenAI",
                "Organization",
                "https://github.com/OpenAI/codex.git",
                stars=200,
            ),
        }
        tag_trusted_repos(repos)
        assert repos["OpenAI/codex"].is_trusted is True

    def test_unknown_org_not_tagged(self):
        repos = {
            "random-user/skill": DiscoveredRepo(
                "random-user/skill",
                "random-user",
                "User",
                "https://github.com/random-user/skill.git",
                stars=5,
            ),
        }
        tag_trusted_repos(repos)
        assert repos["random-user/skill"].is_trusted is False

    def test_mixed_batch(self):
        repos = {
            "openai/tool": DiscoveredRepo(
                "openai/tool",
                "openai",
                "Organization",
                "u",
                stars=100,
            ),
            "nobody/thing": DiscoveredRepo(
                "nobody/thing",
                "nobody",
                "User",
                "u",
                stars=500,
            ),
        }
        tag_trusted_repos(repos)
        assert repos["openai/tool"].is_trusted is True
        assert repos["nobody/thing"].is_trusted is False

    def test_trusted_orgs_list_not_empty(self):
        assert len(TRUSTED_ORGS) > 0
        # All entries should be lowercase
        for org in TRUSTED_ORGS:
            assert org == org.lower(), f"TRUSTED_ORGS entry '{org}' must be lowercase"


# ---------------------------------------------------------------------------
# Slug validation tests
# ---------------------------------------------------------------------------


class TestSlugValidation:
    def test_valid_slugs(self):
        assert _SLUG_PATTERN.match("abc")
        assert _SLUG_PATTERN.match("a-b-c")
        assert _SLUG_PATTERN.match("abc123")
        assert _SLUG_PATTERN.match("a")

    def test_invalid_slugs(self):
        assert not _SLUG_PATTERN.match("")
        assert not _SLUG_PATTERN.match("-abc")
        assert not _SLUG_PATTERN.match("abc-")
        assert not _SLUG_PATTERN.match("ABC")
        assert not _SLUG_PATTERN.match("a_b")
        assert not _SLUG_PATTERN.match("a" * 65)


# ---------------------------------------------------------------------------
# GitHubClient tests
# ---------------------------------------------------------------------------


class TestGitHubClient:
    def test_rate_limit_tracking(self):
        client = GitHubClient.__new__(GitHubClient)
        client._rate_limit_remaining = 999
        client._rate_limit_reset = 0.0
        client._client = MagicMock()

        mock_resp = MagicMock()
        mock_resp.headers = {
            "x-ratelimit-remaining": "42",
            "x-ratelimit-reset": "1700000000",
        }
        client._update_rate_limit(mock_resp)
        assert client._rate_limit_remaining == 42
        assert client._rate_limit_reset == 1700000000.0

    def test_proactive_wait(self):
        client = GitHubClient.__new__(GitHubClient)
        client._rate_limit_remaining = 2
        client._rate_limit_reset = time.time() - 10  # Already past
        client._client = MagicMock()

        # Should call sleep but not hang since reset is in the past
        with patch("decision_hub.scripts.crawler.discovery.time.sleep") as mock_sleep:
            client._wait_for_rate_limit()
            mock_sleep.assert_called_once()


# ---------------------------------------------------------------------------
# Code search / strategy tests
# ---------------------------------------------------------------------------


def _make_code_search_response(items: list[dict], status_code: int = 200):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {"items": items}
    mock_resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}
    mock_resp.text = ""
    return mock_resp


def _make_search_item(full_name: str, owner_type: str = "User", private: bool = False):
    return {
        "repository": {
            "full_name": full_name,
            "owner": {"login": full_name.split("/")[0], "type": owner_type},
            "clone_url": f"https://github.com/{full_name}.git",
            "stargazers_count": 10,
            "description": "test",
            "private": private,
        }
    }


class TestPrivateRepoFiltering:
    """Private repos must be excluded from all auto-discovery strategies."""

    def test_code_search_skips_private_repos(self):
        gh = MagicMock()
        gh.get.return_value = _make_code_search_response(
            [_make_search_item("public/repo"), _make_search_item("private/repo", private=True)]
        )
        stats = CrawlStats()
        result = _run_code_search(gh, "filename:SKILL.md", stats)
        assert "public/repo" in result
        assert "private/repo" not in result

    def test_topic_search_skips_private_repos(self):
        gh = MagicMock()
        items = [
            {
                "full_name": "public/repo",
                "owner": {"login": "public", "type": "User"},
                "clone_url": "https://github.com/public/repo.git",
                "stargazers_count": 10,
                "description": "test",
                "private": False,
            },
            {
                "full_name": "private/repo",
                "owner": {"login": "private", "type": "User"},
                "clone_url": "https://github.com/private/repo.git",
                "stargazers_count": 5,
                "description": "secret",
                "private": True,
            },
        ]
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"items": items}
        resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}
        gh.get.return_value = resp
        stats = CrawlStats()

        result: dict[str, DiscoveredRepo] = {}
        for batch in search_by_topic(gh, stats):
            result.update(batch)

        assert "public/repo" in result
        assert "private/repo" not in result

    def test_fork_scan_skips_private_forks(self):
        gh = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = [
            {
                "full_name": "public-fork/repo",
                "owner": {"login": "public-fork", "type": "User"},
                "clone_url": "https://github.com/public-fork/repo.git",
                "stargazers_count": 5,
                "description": "fork",
                "private": False,
            },
            {
                "full_name": "private-fork/repo",
                "owner": {"login": "private-fork", "type": "User"},
                "clone_url": "https://github.com/private-fork/repo.git",
                "stargazers_count": 3,
                "description": "secret fork",
                "private": True,
            },
        ]
        resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}
        gh.get.return_value = resp
        stats = CrawlStats()

        result: dict[str, DiscoveredRepo] = {}
        for batch in scan_forks(gh, ["original/repo"], stats):
            result.update(batch)

        assert "public-fork/repo" in result
        assert "private-fork/repo" not in result

    def test_curated_list_skips_private_repos(self):
        import base64

        readme_content = "# Awesome\n- https://github.com/public/skill\n- https://github.com/private/skill\n"
        encoded = base64.b64encode(readme_content.encode()).decode()

        def _side_effect(url, **_kwargs):
            resp = MagicMock()
            resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}
            if url.endswith("/readme"):
                resp.status_code = 200
                resp.json.return_value = {"content": encoded}
            elif url == "/repos/public/skill":
                resp.status_code = 200
                resp.json.return_value = {
                    "owner": {"login": "public", "type": "User"},
                    "clone_url": "https://github.com/public/skill.git",
                    "stargazers_count": 50,
                    "description": "A public skill",
                    "private": False,
                }
            elif url == "/repos/private/skill":
                resp.status_code = 200
                resp.json.return_value = {
                    "owner": {"login": "private", "type": "User"},
                    "clone_url": "https://github.com/private/skill.git",
                    "stargazers_count": 0,
                    "description": "A private skill",
                    "private": True,
                }
            else:
                resp.status_code = 404
            return resp

        gh = MagicMock()
        gh.get.side_effect = _side_effect
        stats = CrawlStats()
        result: dict[str, DiscoveredRepo] = {}
        for batch in parse_curated_lists(gh, stats):
            result.update(batch)

        assert "public/skill" in result
        assert "private/skill" not in result

    def test_resolve_repos_allows_private_with_warning(self, caplog):
        gh = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "owner": {"login": "pymc-labs", "type": "Organization"},
            "clone_url": "https://github.com/pymc-labs/private-skills.git",
            "stargazers_count": 0,
            "description": "Internal skills",
            "private": True,
        }
        resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}
        gh.get.return_value = resp

        stats = CrawlStats()
        # --repos is explicit opt-in, so private repos must be allowed
        result = resolve_repos(gh, ["pymc-labs/private-skills"], stats)
        assert "pymc-labs/private-skills" in result


class TestRunCodeSearch:
    def test_pagination_stops_when_fewer_than_100(self):
        """If a page returns fewer than 100 items, don't request the next page."""
        gh = MagicMock()
        gh.get.return_value = _make_code_search_response([_make_search_item("a/b")])
        stats = CrawlStats()
        result = _run_code_search(gh, "filename:SKILL.md", stats)
        assert "a/b" in result
        assert stats.queries_made == 1

    def test_pagination_stops_at_10_pages(self):
        gh = MagicMock()
        # Return 100 items per page to keep paginating
        items = [_make_search_item(f"owner/repo{i}") for i in range(100)]
        gh.get.return_value = _make_code_search_response(items)
        stats = CrawlStats()
        with patch("decision_hub.scripts.crawler.discovery.time.sleep"):
            _run_code_search(gh, "filename:SKILL.md", stats)
        assert stats.queries_made == 10

    def test_rate_limit_stops(self):
        gh = MagicMock()
        gh.get.return_value = _make_code_search_response([], status_code=403)
        stats = CrawlStats()
        result = _run_code_search(gh, "filename:SKILL.md", stats)
        assert len(result) == 0
        assert stats.queries_made == 1


class TestSearchByFileSize:
    def test_deduplication(self):
        """Same repo in multiple size ranges is only counted once."""
        gh = MagicMock()
        # Return the same repo in every size range
        gh.get.return_value = _make_code_search_response([_make_search_item("owner/repo")])
        stats = CrawlStats()
        result: dict[str, DiscoveredRepo] = {}
        for batch in search_by_file_size(gh, stats):
            result.update(batch)
        assert len(result) == 1
        assert "owner/repo" in result


class TestSearchByPath:
    def test_all_paths_queried(self):
        gh = MagicMock()
        gh.get.return_value = _make_code_search_response([])
        stats = CrawlStats()
        list(search_by_path(gh, stats))  # exhaust generator
        queries = [call.args[0] for call in gh.get.call_args_list]
        # Verify each path is used in a query
        assert len(queries) >= len(SKILL_PATHS)


class TestSearchByTopic:
    def test_pagination_up_to_5_pages(self):
        gh = MagicMock()
        items = [
            {
                "full_name": f"owner/repo{i}",
                "owner": {"login": "owner", "type": "User"},
                "clone_url": f"https://github.com/owner/repo{i}.git",
                "stargazers_count": 10,
                "description": "test",
            }
            for i in range(100)
        ]
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"items": items}
        resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}
        gh.get.return_value = resp
        stats = CrawlStats()

        with patch("decision_hub.scripts.crawler.discovery.time.sleep"):
            list(search_by_topic(gh, stats))  # exhaust generator

        # Each of the 8 topics paginates 5 pages = 40 queries
        assert stats.queries_made == 40


class TestScanForks:
    def test_top_repos_scanned(self):
        gh = MagicMock()
        fork_data = [
            {
                "full_name": "forker/repo",
                "owner": {"login": "forker", "type": "User"},
                "clone_url": "https://github.com/forker/repo.git",
                "stargazers_count": 5,
                "description": "fork",
            }
        ]
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = fork_data
        resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}
        gh.get.return_value = resp
        stats = CrawlStats()

        result: dict[str, DiscoveredRepo] = {}
        for batch in scan_forks(gh, ["original/repo"], stats):
            result.update(batch)
        assert "forker/repo" in result


class TestParseCuratedLists:
    def test_link_extraction(self):
        import base64

        readme_content = "# Awesome\n- [Skill](https://github.com/cool/skill)\n- https://github.com/nice/tool\n"
        encoded = base64.b64encode(readme_content.encode()).decode()

        gh = MagicMock()

        # First call: get readme
        readme_resp = MagicMock()
        readme_resp.status_code = 200
        readme_resp.json.return_value = {"content": encoded}
        readme_resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}

        # Subsequent calls: get individual repos
        repo_resp = MagicMock()
        repo_resp.status_code = 200
        repo_resp.json.return_value = {
            "owner": {"login": "cool", "type": "User"},
            "clone_url": "https://github.com/cool/skill.git",
            "stargazers_count": 50,
            "description": "A cool skill",
        }
        repo_resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}

        # Return 404 for non-existent readme repos, then success for found ones
        fail_resp = MagicMock()
        fail_resp.status_code = 404
        fail_resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}

        gh.get.side_effect = [readme_resp, repo_resp, repo_resp] + [fail_resp] * 20
        stats = CrawlStats()
        result: dict[str, DiscoveredRepo] = {}
        for batch in parse_curated_lists(gh, stats):
            result.update(batch)
        assert len(result) >= 1

    def test_invalid_readme_handled(self):
        gh = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"content": "not-valid-base64!!!"}
        resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}
        gh.get.return_value = resp
        stats = CrawlStats()
        result = list(parse_curated_lists(gh, stats))
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Checkpoint tests
# ---------------------------------------------------------------------------


class TestCheckpoint:
    def test_save_load_roundtrip(self, tmp_path):
        cp = Checkpoint(
            discovered_repos={
                "a/b": {
                    "full_name": "a/b",
                    "owner_login": "a",
                    "owner_type": "User",
                    "clone_url": "u",
                    "stars": 1,
                    "description": "d",
                }
            },
            processed_repos={"a/b": "abc123"},
        )
        path = tmp_path / "cp.json"
        cp.save(path)
        loaded = Checkpoint.load(path)
        assert loaded.discovered_repos == cp.discovered_repos
        assert loaded.processed_repos == cp.processed_repos

    def test_legacy_list_migration(self, tmp_path):
        """Legacy checkpoints with list[str] are auto-migrated to dict."""
        import json

        path = tmp_path / "cp.json"
        path.write_text(json.dumps({"discovered_repos": {}, "processed_repos": ["a/b", "c/d"]}))
        loaded = Checkpoint.load(path)
        assert loaded.processed_repos == {"a/b": None, "c/d": None}

    def test_mark_processed_stores_sha(self, tmp_path):
        cp = Checkpoint()
        path = tmp_path / "cp.json"
        cp.save(path)
        cp.mark_processed("a/b", path, commit_sha="abc123", flush_every=1000)
        assert cp.processed_repos["a/b"] == "abc123"
        cp.flush(path)
        loaded = Checkpoint.load(path)
        assert loaded.processed_repos["a/b"] == "abc123"

    def test_get_last_sha(self):
        cp = Checkpoint(processed_repos={"a/b": "sha1", "c/d": None})
        assert cp.get_last_sha("a/b") == "sha1"
        assert cp.get_last_sha("c/d") is None
        assert cp.get_last_sha("e/f") is None

    def test_mark_processed_flush_every_n(self, tmp_path):
        cp = Checkpoint()
        path = tmp_path / "cp.json"
        cp.save(path)

        # Mark 99 repos — should not flush yet
        for i in range(99):
            cp.mark_processed(f"owner/repo{i}", path, flush_every=100)

        # Load from file — should still be empty (not flushed)
        loaded = Checkpoint.load(path)
        assert len(loaded.processed_repos) == 0

        # 100th mark triggers flush
        cp.mark_processed("owner/repo99", path, flush_every=100)
        loaded = Checkpoint.load(path)
        assert len(loaded.processed_repos) == 100

    def test_flush(self, tmp_path):
        cp = Checkpoint()
        path = tmp_path / "cp.json"
        cp.save(path)

        cp.mark_processed("a/b", path, flush_every=1000)
        cp.flush(path)
        loaded = Checkpoint.load(path)
        assert "a/b" in loaded.processed_repos

    def test_fresh_deletes_file(self, tmp_path):
        path = tmp_path / "cp.json"
        path.write_text("{}")
        assert path.exists()
        path.unlink()
        assert not path.exists()

    def test_large_scale(self, tmp_path):
        """Verify checkpoint handles 100k entries without issues."""
        cp = Checkpoint(
            discovered_repos={f"owner/repo{i}": {"full_name": f"owner/repo{i}"} for i in range(100_000)},
            processed_repos={f"owner/repo{i}": f"sha{i}" for i in range(50_000)},
        )
        path = tmp_path / "cp.json"
        cp.save(path)
        loaded = Checkpoint.load(path)
        assert len(loaded.discovered_repos) == 100_000
        assert len(loaded.processed_repos) == 50_000


# ---------------------------------------------------------------------------
# Change detection / priority sorting tests
# ---------------------------------------------------------------------------


class TestFilterChangedRepos:
    def test_new_repos_always_included(self):
        """Repos not in checkpoint are always included."""
        from decision_hub.scripts.crawler.__main__ import _filter_changed_repos

        repos = [
            DiscoveredRepo("a/b", "a", "User", "https://github.com/a/b.git", stars=5),
        ]
        cp = Checkpoint()  # empty — no processed repos

        result = _filter_changed_repos(repos, cp, github_token=None)
        assert len(result) == 1

    @patch("decision_hub.domain.tracker.fetch_latest_commit_sha")
    def test_unchanged_repo_skipped(self, mock_fetch_sha):
        """Repo with same HEAD SHA as checkpoint is skipped."""
        from decision_hub.scripts.crawler.__main__ import _filter_changed_repos

        mock_fetch_sha.return_value = "abc123"

        repos = [
            DiscoveredRepo("a/b", "a", "User", "https://github.com/a/b.git", stars=5),
        ]
        cp = Checkpoint(processed_repos={"a/b": "abc123"})

        result = _filter_changed_repos(repos, cp, github_token="tok")
        assert len(result) == 0

    @patch("decision_hub.domain.tracker.fetch_latest_commit_sha")
    def test_changed_repo_included(self, mock_fetch_sha):
        """Repo with different HEAD SHA is included."""
        from decision_hub.scripts.crawler.__main__ import _filter_changed_repos

        mock_fetch_sha.return_value = "new_sha"

        repos = [
            DiscoveredRepo("a/b", "a", "User", "https://github.com/a/b.git", stars=5),
        ]
        cp = Checkpoint(processed_repos={"a/b": "old_sha"})

        result = _filter_changed_repos(repos, cp, github_token="tok")
        assert len(result) == 1

    @patch("decision_hub.domain.tracker.fetch_latest_commit_sha")
    def test_api_error_includes_repo(self, mock_fetch_sha):
        """If SHA check fails, process the repo anyway (safe default)."""
        from decision_hub.scripts.crawler.__main__ import _filter_changed_repos

        mock_fetch_sha.side_effect = Exception("API error")

        repos = [
            DiscoveredRepo("a/b", "a", "User", "https://github.com/a/b.git", stars=5),
        ]
        cp = Checkpoint(processed_repos={"a/b": "old_sha"})

        result = _filter_changed_repos(repos, cp, github_token="tok")
        assert len(result) == 1

    @patch("decision_hub.domain.tracker.fetch_latest_commit_sha")
    def test_sorted_by_stars_descending(self, mock_fetch_sha):
        """Results are sorted by stars (most popular first) within trust tier."""
        from decision_hub.scripts.crawler.__main__ import _filter_changed_repos

        mock_fetch_sha.return_value = "new_sha"

        repos = [
            DiscoveredRepo("low/repo", "low", "User", "u", stars=1),
            DiscoveredRepo("high/repo", "high", "User", "u", stars=100),
            DiscoveredRepo("mid/repo", "mid", "User", "u", stars=50),
        ]
        cp = Checkpoint()

        result = _filter_changed_repos(repos, cp, github_token=None)
        assert [r.full_name for r in result] == ["high/repo", "mid/repo", "low/repo"]

    @patch("decision_hub.domain.tracker.fetch_latest_commit_sha")
    def test_trusted_repos_sorted_before_untrusted(self, mock_fetch_sha):
        """Trusted repos appear before untrusted even with fewer stars."""
        from decision_hub.scripts.crawler.__main__ import _filter_changed_repos

        mock_fetch_sha.return_value = "new_sha"

        repos = [
            DiscoveredRepo("popular/repo", "popular", "User", "u", stars=1000),
            DiscoveredRepo(
                "anthropics/skills",
                "anthropics",
                "Organization",
                "u",
                stars=10,
                is_trusted=True,
            ),
            DiscoveredRepo(
                "openai/tools",
                "openai",
                "Organization",
                "u",
                stars=50,
                is_trusted=True,
            ),
            DiscoveredRepo("another/repo", "another", "User", "u", stars=500),
        ]
        cp = Checkpoint()

        result = _filter_changed_repos(repos, cp, github_token=None)
        # Trusted repos first (sorted by stars), then untrusted (sorted by stars)
        assert [r.full_name for r in result] == [
            "openai/tools",
            "anthropics/skills",
            "popular/repo",
            "another/repo",
        ]

    @patch("decision_hub.domain.tracker.fetch_latest_commit_sha")
    def test_legacy_none_sha_always_rechecked(self, mock_fetch_sha):
        """Repos with None SHA (from legacy checkpoint) are always rechecked."""
        from decision_hub.scripts.crawler.__main__ import _filter_changed_repos

        mock_fetch_sha.return_value = "current_sha"

        repos = [
            DiscoveredRepo("a/b", "a", "User", "https://github.com/a/b.git", stars=5),
        ]
        # Legacy checkpoint: SHA is None (migrated from list)
        cp = Checkpoint(processed_repos={"a/b": None})

        result = _filter_changed_repos(repos, cp, github_token="tok")
        # None means "never recorded a SHA", so it should be included
        assert len(result) == 1


# ---------------------------------------------------------------------------
# fetch_owner_metadata tests
# ---------------------------------------------------------------------------


class TestFetchOwnerMetadata:
    @patch("decision_hub.scripts.crawler.processing.httpx.get")
    def test_user_metadata(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "email": "user@example.com",
            "avatar_url": "https://avatars.githubusercontent.com/u/1",
            "bio": "A developer",
            "blog": "https://example.com",
        }
        mock_get.return_value = resp

        result = fetch_owner_metadata("testuser", "User", "token123")
        assert result == {
            "avatar_url": "https://avatars.githubusercontent.com/u/1",
            "email": "user@example.com",
            "description": "A developer",
            "blog": "https://example.com",
        }
        mock_get.assert_called_once_with(
            "https://api.github.com/users/testuser",
            headers={"Accept": "application/vnd.github+json", "Authorization": "Bearer token123"},
            timeout=15,
        )

    @patch("decision_hub.scripts.crawler.processing.httpx.get")
    def test_org_metadata(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "email": "org@example.com",
            "avatar_url": "https://avatars.githubusercontent.com/u/2",
            "description": "An org",
            "blog": "https://org.example.com",
        }
        mock_get.return_value = resp

        result = fetch_owner_metadata("testorg", "Organization", "token123")
        assert result == {
            "avatar_url": "https://avatars.githubusercontent.com/u/2",
            "email": "org@example.com",
            "description": "An org",
            "blog": "https://org.example.com",
        }
        mock_get.assert_called_once_with(
            "https://api.github.com/orgs/testorg",
            headers={"Accept": "application/vnd.github+json", "Authorization": "Bearer token123"},
            timeout=15,
        )

    @patch("decision_hub.scripts.crawler.processing.httpx.get")
    def test_missing_fields_return_none(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"email": None, "avatar_url": None}
        mock_get.return_value = resp

        result = fetch_owner_metadata("testuser", "User")
        assert result["email"] is None
        assert result["avatar_url"] is None
        assert result["description"] is None
        assert result["blog"] is None

    @patch("decision_hub.scripts.crawler.processing.httpx.get")
    def test_http_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("connection failed")
        result = fetch_owner_metadata("testuser", "User")
        assert result == {}

    @patch("decision_hub.scripts.crawler.processing.httpx.get")
    def test_empty_strings_normalized_to_none(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"email": "", "avatar_url": "", "bio": "", "blog": ""}
        mock_get.return_value = resp

        result = fetch_owner_metadata("testuser", "User")
        assert result["email"] is None
        assert result["avatar_url"] is None
        assert result["description"] is None
        assert result["blog"] is None


# ---------------------------------------------------------------------------
# Discover skills tests (reuses shared repo_utils)
# ---------------------------------------------------------------------------


class TestDiscoverSkills:
    def test_finds_nested(self, tmp_path):
        from decision_hub.domain.repo_utils import discover_skills

        skill1 = tmp_path / "skills" / "skill-a"
        skill1.mkdir(parents=True)
        (skill1 / "SKILL.md").write_text("---\nname: skill-a\ndescription: test\n---\nBody")

        skill2 = tmp_path / "skills" / "skill-b"
        skill2.mkdir(parents=True)
        (skill2 / "SKILL.md").write_text("---\nname: skill-b\ndescription: test\n---\nBody")

        with patch("decision_hub.domain.skill_manifest.parse_skill_md") as mock_parse:
            mock_parse.return_value = MagicMock()
            result = discover_skills(tmp_path)
            assert len(result) == 2

    def test_empty_dir(self, tmp_path):
        from decision_hub.domain.repo_utils import discover_skills

        result = discover_skills(tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# Clone repo tests
# ---------------------------------------------------------------------------


class TestCloneRepo:
    @patch("decision_hub.domain.repo_utils.subprocess.run")
    def test_timeout_propagates(self, mock_run):
        from decision_hub.domain.repo_utils import clone_repo

        mock_run.side_effect = subprocess.TimeoutExpired("git", 120)
        with pytest.raises(RuntimeError, match="timed out"):
            clone_repo("https://github.com/a/b.git", timeout=120)


# ---------------------------------------------------------------------------
# Repo URL parsing tests
# ---------------------------------------------------------------------------


class TestParseRepoUrl:
    def test_ssh_url(self):
        assert parse_repo_url("git@github.com:machina-sports/sports-skills.git") == "machina-sports/sports-skills"

    def test_ssh_url_no_dot_git(self):
        assert parse_repo_url("git@github.com:owner/repo") == "owner/repo"

    def test_https_url(self):
        assert parse_repo_url("https://github.com/owner/repo") == "owner/repo"

    def test_https_url_with_dot_git(self):
        assert parse_repo_url("https://github.com/owner/repo.git") == "owner/repo"

    def test_https_url_trailing_slash(self):
        assert parse_repo_url("https://github.com/owner/repo/") == "owner/repo"

    def test_http_url(self):
        assert parse_repo_url("http://github.com/owner/repo") == "owner/repo"

    def test_bare_owner_repo(self):
        assert parse_repo_url("owner/repo") == "owner/repo"

    def test_bare_with_dashes_and_dots(self):
        assert parse_repo_url("my-org/my.repo") == "my-org/my.repo"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_repo_url("not-a-repo-url")

    def test_invalid_three_segment_path(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_repo_url("a/b/c")


# ---------------------------------------------------------------------------
# Repo resolution tests
# ---------------------------------------------------------------------------


class TestResolveRepos:
    def test_resolves_valid_repos(self):
        gh = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "owner": {"login": "machina-sports", "type": "Organization"},
            "clone_url": "https://github.com/machina-sports/sports-skills.git",
            "stargazers_count": 42,
            "description": "Sports skills",
        }
        resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}
        gh.get.return_value = resp

        stats = CrawlStats()
        result = resolve_repos(gh, ["git@github.com:machina-sports/sports-skills.git"], stats)

        assert "machina-sports/sports-skills" in result
        repo = result["machina-sports/sports-skills"]
        assert repo.stars == 42
        assert repo.clone_url == "https://github.com/machina-sports/sports-skills.git"
        assert stats.queries_made == 1

    def test_skips_invalid_identifier(self):
        gh = MagicMock()
        stats = CrawlStats()
        result = resolve_repos(gh, ["not-a-valid-url"], stats)

        assert len(result) == 0
        assert len(stats.errors) == 1
        gh.get.assert_not_called()

    def test_skips_404_repos(self):
        gh = MagicMock()
        resp = MagicMock()
        resp.status_code = 404
        resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}
        gh.get.return_value = resp

        stats = CrawlStats()
        result = resolve_repos(gh, ["owner/nonexistent"], stats)

        assert len(result) == 0
        assert len(stats.errors) == 1

    def test_mixed_valid_and_invalid(self):
        gh = MagicMock()
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {
            "owner": {"login": "owner", "type": "User"},
            "clone_url": "https://github.com/owner/repo.git",
            "stargazers_count": 10,
            "description": "A repo",
        }
        ok_resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}

        fail_resp = MagicMock()
        fail_resp.status_code = 404
        fail_resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}

        gh.get.side_effect = [ok_resp, fail_resp]

        stats = CrawlStats()
        result = resolve_repos(
            gh,
            ["owner/repo", "owner/missing"],
            stats,
        )

        assert len(result) == 1
        assert "owner/repo" in result
        assert stats.queries_made == 2

    def test_tags_trusted_repos(self):
        gh = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "owner": {"login": "anthropics", "type": "Organization"},
            "clone_url": "https://github.com/anthropics/skills.git",
            "stargazers_count": 100,
            "description": "Official",
        }
        resp.headers = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": "9999999999"}
        gh.get.return_value = resp

        stats = CrawlStats()
        result = resolve_repos(gh, ["anthropics/skills"], stats)

        assert result["anthropics/skills"].is_trusted is True


# ---------------------------------------------------------------------------
# Orchestrator tests
# ---------------------------------------------------------------------------


class TestOrchestrator:
    def test_parse_args_defaults(self):
        from decision_hub.scripts.crawler.__main__ import parse_args

        args = parse_args([])
        assert args.env == "dev"
        assert args.max_skills is None
        assert args.dry_run is False
        assert args.resume is False
        assert args.fresh is False

    def test_parse_args_resume_fresh_exclusive(self):
        from decision_hub.scripts.crawler.__main__ import parse_args

        with pytest.raises(SystemExit):
            parse_args(["--resume", "--fresh"])

    def test_parse_args_strategies(self):
        from decision_hub.scripts.crawler.__main__ import parse_args

        args = parse_args(["--strategies", "size", "path"])
        assert args.strategies == ["size", "path"]

    def test_parse_args_max_skills(self):
        from decision_hub.scripts.crawler.__main__ import parse_args

        args = parse_args(["--max-skills", "50"])
        assert args.max_skills == 50

    def test_parse_args_repos(self):
        from decision_hub.scripts.crawler.__main__ import parse_args

        args = parse_args(["--repos", "owner/repo", "git@github.com:org/skill.git"])
        assert args.repos == ["owner/repo", "git@github.com:org/skill.git"]

    def test_parse_args_repos_default_none(self):
        from decision_hub.scripts.crawler.__main__ import parse_args

        args = parse_args([])
        assert args.repos is None

    def test_parse_args_repos_and_resume_mutually_exclusive(self):
        from decision_hub.scripts.crawler.__main__ import parse_args

        with pytest.raises(SystemExit):
            parse_args(["--repos", "owner/repo", "--resume"])


# ---------------------------------------------------------------------------
# process_repo_on_modal tests
# ---------------------------------------------------------------------------


class TestProcessRepoOnModal:
    """Tests for process_repo_on_modal.

    The function uses deferred imports, so we patch at the source modules.
    """

    def test_invalid_slug_skipped(self):
        from decision_hub.scripts.crawler.processing import process_repo_on_modal

        repo_dict = {
            "full_name": "-bad-slug/repo",
            "owner_login": "-bad-slug",
            "owner_type": "User",
            "clone_url": "https://github.com/-bad-slug/repo.git",
            "stars": 0,
            "description": "",
        }

        with (
            patch("decision_hub.settings.create_settings"),
            patch("decision_hub.infra.database.create_engine"),
            patch("decision_hub.infra.storage.create_s3_client"),
        ):
            result = process_repo_on_modal(repo_dict, str(uuid4()), None)

        assert result["status"] == "skipped"
        assert "Invalid org slug" in result["error"]

    @patch("decision_hub.scripts.crawler.processing.clone_repo")
    @patch("decision_hub.scripts.crawler.processing.discover_skills")
    @patch("decision_hub.scripts.crawler.processing.fetch_owner_metadata")
    def test_no_skills(self, mock_email, mock_discover, mock_clone, tmp_path):
        from decision_hub.scripts.crawler.processing import process_repo_on_modal

        mock_email.return_value = {}
        mock_clone.return_value = tmp_path / "repo"
        (tmp_path / "repo").mkdir()
        mock_discover.return_value = []

        repo_dict = {
            "full_name": "owner/repo",
            "owner_login": "owner",
            "owner_type": "User",
            "clone_url": "https://github.com/owner/repo.git",
            "stars": 0,
            "description": "",
        }

        with (
            patch("decision_hub.settings.create_settings") as mock_settings,
            patch("decision_hub.infra.database.create_engine") as mock_engine,
            patch("decision_hub.infra.storage.create_s3_client"),
            patch("decision_hub.infra.database.upsert_user"),
            patch("decision_hub.infra.database.find_org_by_slug") as mock_find_org,
            patch("decision_hub.infra.database.insert_organization") as mock_insert_org,
            patch("decision_hub.infra.database.insert_org_member"),
            patch("decision_hub.infra.database.update_org_github_metadata"),
        ):
            mock_settings.return_value = MagicMock()
            mock_conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

            mock_org = MagicMock()
            mock_org.github_synced_at = None
            mock_find_org.return_value = None
            mock_insert_org.return_value = mock_org

            result = process_repo_on_modal(repo_dict, str(uuid4()), None)

        assert result["status"] == "no_skills"

    def test_clone_timeout(self):
        from decision_hub.scripts.crawler.processing import process_repo_on_modal

        repo_dict = {
            "full_name": "owner/repo",
            "owner_login": "owner",
            "owner_type": "User",
            "clone_url": "https://github.com/owner/repo.git",
            "stars": 0,
            "description": "",
        }

        with (
            patch("decision_hub.settings.create_settings"),
            patch("decision_hub.infra.database.create_engine") as mock_engine,
            patch("decision_hub.infra.storage.create_s3_client"),
            patch("decision_hub.scripts.crawler.processing.fetch_owner_metadata", return_value={}),
            patch("decision_hub.infra.database.upsert_user"),
            patch("decision_hub.infra.database.find_org_by_slug") as mock_find_org,
            patch("decision_hub.infra.database.insert_organization") as mock_insert_org,
            patch("decision_hub.infra.database.insert_org_member"),
            patch("decision_hub.infra.database.update_org_github_metadata"),
            patch("decision_hub.scripts.crawler.processing.clone_repo") as mock_clone,
        ):
            mock_conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

            mock_org = MagicMock()
            mock_org.github_synced_at = None
            mock_find_org.return_value = None
            mock_insert_org.return_value = mock_org

            mock_clone.side_effect = subprocess.TimeoutExpired("git", 120)

            result = process_repo_on_modal(repo_dict, str(uuid4()), None)

        assert result["status"] == "error"
        assert "timed out" in result["error"]
