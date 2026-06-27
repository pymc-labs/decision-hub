"""Tests for the batch_update_github_* DB helpers.

These functions used to issue one UPDATE per repo, an N+1 over the
tracker resolution set. They were rewritten to a single multi-row
UPDATE FROM (VALUES ...) statement. The tests below verify that:

  * Empty input is a no-op (no DB call).
  * Non-empty input is collapsed to exactly one ``conn.execute`` call.
  * The compiled SQL contains the expected VALUES rows and uses
    ``LIKE ... ESCAPE '\\'`` so repo names with ``_`` (a legitimate
    GitHub character that is also a SQL LIKE wildcard) only match
    themselves.

The tests are pure compile checks against the PostgreSQL dialect, so
they don't need a live database.
"""

from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from decision_hub.infra.database import (
    batch_update_github_repo_metadata,
    batch_update_github_stars,
)


def _compile(call) -> str:
    """Render the first positional argument to a conn.execute() call as SQL."""
    stmt = call.args[0]
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class TestBatchUpdateGithubStars:
    def test_empty_input_is_noop(self):
        conn = MagicMock()
        batch_update_github_stars(conn, {})
        conn.execute.assert_not_called()

    def test_single_execute_for_many_repos(self):
        """N repos should compile to ONE statement, not N statements."""
        conn = MagicMock()
        repo_stars = {
            "https://github.com/foo/bar": 1,
            "https://github.com/foo/baz": 2,
            "https://github.com/qux/quux": 3,
        }
        batch_update_github_stars(conn, repo_stars)
        assert conn.execute.call_count == 1

    def test_compiled_sql_contains_all_values_rows(self):
        conn = MagicMock()
        repo_stars = {
            "https://github.com/foo/bar": 7,
            "https://github.com/foo/baz": 13,
        }
        batch_update_github_stars(conn, repo_stars)
        sql = _compile(conn.execute.call_args)
        assert "UPDATE skills" in sql
        assert "FROM (VALUES" in sql
        assert "https://github.com/foo/bar" in sql
        assert "https://github.com/foo/baz" in sql
        # Star counts appear as literal integers in the VALUES list
        assert ", 7" in sql or ",7" in sql
        assert ", 13" in sql or ",13" in sql

    def test_like_pattern_escapes_underscore(self):
        r"""Repo names like ``my_repo`` must not match ``myXrepo``.

        Without escaping ``_`` (a LIKE wildcard meaning any single char),
        a star update for ``foo/my_repo`` would also overwrite skills
        sourced from ``foo/myXrepo``. The new implementation pre-escapes
        the prefix and uses ``LIKE ... ESCAPE '\\'``.

        Note: PostgreSQL's literal-binds renderer doubles every backslash
        when emitting standard string literals, so ``\_`` in the LIKE
        pattern appears as ``\\_`` in the compiled SQL text. The
        important part is that the underscore is escaped at all.
        """
        conn = MagicMock()
        batch_update_github_stars(conn, {"https://github.com/foo/my_repo": 99})
        sql = _compile(conn.execute.call_args)
        # Look for the LIKE pattern with at least one backslash before
        # the underscore. The exact backslash count depends on the SQL
        # string-literal escaping rules of the dialect.
        assert "my\\_repo" in sql or "my\\\\_repo" in sql
        assert "ESCAPE" in sql

    def test_like_pattern_escapes_percent(self):
        conn = MagicMock()
        # ``%`` in a URL is unusual but the escape must still work.
        batch_update_github_stars(conn, {"https://github.com/foo/100%repo": 1})
        sql = _compile(conn.execute.call_args)
        # ``%`` becomes ``\%`` in the LIKE pattern. Same backslash-doubling
        # caveat as the underscore test.
        assert "\\%" in sql or "\\\\%" in sql


class TestBatchUpdateGithubRepoMetadata:
    def test_empty_input_is_noop(self):
        conn = MagicMock()
        batch_update_github_repo_metadata(conn, {})
        conn.execute.assert_not_called()

    def test_single_execute_for_many_repos(self):
        conn = MagicMock()
        repo_metadata = {
            f"https://github.com/foo/repo-{i}": {
                "forks": i,
                "watchers": i * 2,
                "is_archived": i % 2 == 0,
                "license": "MIT",
            }
            for i in range(5)
        }
        batch_update_github_repo_metadata(conn, repo_metadata)
        assert conn.execute.call_count == 1

    def test_compiled_sql_sets_all_four_columns(self):
        conn = MagicMock()
        repo_metadata = {
            "https://github.com/foo/bar": {
                "forks": 1,
                "watchers": 2,
                "is_archived": True,
                "license": "Apache-2.0",
            }
        }
        batch_update_github_repo_metadata(conn, repo_metadata)
        sql = _compile(conn.execute.call_args)
        assert "github_forks=v.forks" in sql
        assert "github_watchers=v.watchers" in sql
        assert "github_is_archived=v.is_archived" in sql
        assert "github_license=v.license" in sql
        assert "Apache-2.0" in sql

    def test_handles_missing_metadata_fields(self):
        """Partial dicts (missing keys) should compile to NULL in the VALUES row."""
        conn = MagicMock()
        # Only ``forks`` provided — others should default to None.
        batch_update_github_repo_metadata(conn, {"https://github.com/foo/bar": {"forks": 5}})
        sql = _compile(conn.execute.call_args)
        assert "5" in sql
        # The other columns appear as NULL literals.
        assert "NULL" in sql
