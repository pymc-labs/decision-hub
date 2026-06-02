"""Tests for fetch_skills_by_repo and _normalize_repo_url."""

from unittest.mock import MagicMock, patch

from decision_hub.infra.database import (
    _normalize_repo_url,
    batch_update_github_repo_metadata,
    batch_update_github_stars,
    fetch_skills_by_repo,
)

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
        mock_row.has_tracker = True

        conn = MagicMock()
        conn.execute.return_value.all.return_value = [mock_row]

        results = fetch_skills_by_repo(conn, "https://github.com/acme/repo")

        assert len(results) == 1
        assert results[0]["org_slug"] == "acme"
        assert results[0]["skill_name"] == "skill-a"
        assert results[0]["has_tracker"] is True
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


# ---------------------------------------------------------------------------
# batch_update_github_stars / batch_update_github_repo_metadata
#
# Regression: the LIKE pattern used to be ``f"{repo_url}/%"`` with no
# escape character.  GitHub repo URLs commonly contain ``_`` (e.g.
# ``github.com/foo_bar/baz``), and ``_`` is a single-char LIKE wildcard,
# so an unrelated repo like ``github.com/fooXbar/baz`` would match and
# overwrite the stars / metadata of the wrong skill.  We render the
# generated SQL with ``literal_binds`` to assert the wildcards are
# escaped and ``ESCAPE '\'`` is in the statement.
# ---------------------------------------------------------------------------


def _render_calls(conn_mock: MagicMock) -> list[str]:
    """Render every SQL statement executed against ``conn_mock``.

    SQLAlchemy statements expose ``.compile(compile_kwargs={"literal_binds": True})``
    which inlines parameters, giving us a string we can substring-match.
    """
    rendered = []
    for call in conn_mock.execute.call_args_list:
        stmt = call.args[0]
        rendered.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
    return rendered


class TestBatchUpdateGithubStarsLikeEscape:
    def test_escapes_underscore_wildcards_in_repo_url(self) -> None:
        """A repo URL containing ``_`` must not match cross-org repos.

        Before the fix the WHERE clause was ``source_repo_url LIKE
        'https://github.com/foo_bar/baz/%'`` -- the unescaped ``_`` matched
        any single character, so a skill under ``github.com/fooXbar/baz``
        would have its stars overwritten.
        """
        conn = MagicMock()
        batch_update_github_stars(conn, {"https://github.com/foo_bar/baz": 42})

        rendered = _render_calls(conn)
        assert len(rendered) == 1
        sql = rendered[0]
        # The literal underscores in the repo URL are escaped.
        assert "foo\\_bar" in sql
        # And the LIKE escape character is declared.
        assert "ESCAPE '\\'" in sql

    def test_escapes_percent_wildcards(self) -> None:
        """A repo URL containing ``%`` must not be re-interpreted as a wildcard."""
        conn = MagicMock()
        batch_update_github_stars(conn, {"https://github.com/a%b/c": 1})

        sql = _render_calls(conn)[0]
        assert "a\\%b" in sql


class TestBatchUpdateGithubRepoMetadataLikeEscape:
    def test_escapes_underscore_wildcards_in_repo_url(self) -> None:
        conn = MagicMock()
        batch_update_github_repo_metadata(
            conn,
            {
                "https://github.com/foo_bar/baz": {
                    "forks": 1,
                    "watchers": 2,
                    "is_archived": False,
                    "license": "MIT",
                }
            },
        )

        sql = _render_calls(conn)[0]
        assert "foo\\_bar" in sql
        assert "ESCAPE '\\'" in sql
