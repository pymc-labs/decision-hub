"""Tests for fetch_skills_by_repo and _normalize_repo_url."""

from unittest.mock import MagicMock, patch

from decision_hub.infra.database import _normalize_repo_url, fetch_skills_by_repo

# ---------------------------------------------------------------------------
# _normalize_repo_url
# ---------------------------------------------------------------------------


class TestNormalizeRepoUrl:
    def test_strips_trailing_slash(self):
        assert _normalize_repo_url("https://github.com/acme/repo/") == "https://github.com/acme/repo"

    def test_strips_dot_git_suffix(self):
        assert _normalize_repo_url("https://github.com/acme/repo.git") == "https://github.com/acme/repo"

    def test_strips_dot_git_and_trailing_slash(self):
        assert _normalize_repo_url("https://github.com/acme/repo.git/") == "https://github.com/acme/repo"

    def test_already_clean_url_unchanged(self):
        assert _normalize_repo_url("https://github.com/acme/repo") == "https://github.com/acme/repo"

    def test_multiple_trailing_slashes(self):
        assert _normalize_repo_url("https://github.com/acme/repo///") == "https://github.com/acme/repo"


# ---------------------------------------------------------------------------
# fetch_skills_by_repo
# ---------------------------------------------------------------------------


class TestFetchSkillsByRepo:
    @patch("decision_hub.infra.database._apply_visibility_filter", side_effect=lambda stmt, *a, **kw: stmt)
    def test_returns_skill_summaries(self, _mock_vis):
        """Verify fetch_skills_by_repo executes a query and maps rows."""
        mock_row = MagicMock()
        mock_row._mapping = {
            "org_slug": "acme",
            "skill_name": "skill-a",
            "description": "A skill",
            "download_count": 5,
            "category": "Testing",
            "visibility": "public",
            "source_repo_url": "https://github.com/acme/repo",
            "manifest_path": None,
            "source_repo_removed": False,
            "github_stars": 10,
            "github_forks": 2,
            "github_watchers": 3,
            "github_is_archived": False,
            "github_license": "MIT",
            "latest_version": "1.0.0",
            "eval_status": "A",
            "gauntlet_summary": None,
            "created_at": None,
            "published_by": "testuser",
            "is_personal_org": False,
        }

        conn = MagicMock()
        conn.execute.return_value.all.return_value = [mock_row]

        results = fetch_skills_by_repo(conn, "https://github.com/acme/repo")

        assert len(results) == 1
        assert results[0]["org_slug"] == "acme"
        assert results[0]["skill_name"] == "skill-a"
        conn.execute.assert_called_once()

    @patch("decision_hub.infra.database._apply_visibility_filter", side_effect=lambda stmt, *a, **kw: stmt)
    def test_returns_empty_for_unknown_repo(self, _mock_vis):
        """Unknown repo URL returns empty list."""
        conn = MagicMock()
        conn.execute.return_value.all.return_value = []

        results = fetch_skills_by_repo(conn, "https://github.com/no/such")

        assert results == []

    @patch("decision_hub.infra.database.list_granted_skill_ids", return_value=[])
    @patch("decision_hub.infra.database._apply_visibility_filter", side_effect=lambda stmt, *a, **kw: stmt)
    def test_passes_user_org_ids_for_visibility(self, _mock_vis, mock_granted):
        """When user_org_ids is provided, granted skill IDs are fetched."""
        from uuid import uuid4

        conn = MagicMock()
        conn.execute.return_value.all.return_value = []
        org_ids = [uuid4()]

        fetch_skills_by_repo(conn, "https://github.com/acme/repo", user_org_ids=org_ids)

        mock_granted.assert_called_once_with(conn, org_ids)

    @patch("decision_hub.infra.database._apply_visibility_filter", side_effect=lambda stmt, *a, **kw: stmt)
    def test_does_not_fetch_grants_without_user_org_ids(self, _mock_vis):
        """When user_org_ids is None, granted skill IDs are not fetched."""
        conn = MagicMock()
        conn.execute.return_value.all.return_value = []

        with patch("decision_hub.infra.database.list_granted_skill_ids") as mock_granted:
            fetch_skills_by_repo(conn, "https://github.com/acme/repo")
            mock_granted.assert_not_called()
