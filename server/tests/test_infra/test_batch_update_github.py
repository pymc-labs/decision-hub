"""Tests for batch_update_github_stars / batch_update_github_repo_metadata LIKE escaping.

Regression coverage for the bug where an unescaped ``LIKE '<url>/%'`` pattern
would treat ``_`` characters in repo URLs (e.g. ``pymc_labs``) as single-char
wildcards and clobber unrelated repos' star/fork/watcher counts.
"""

from unittest.mock import MagicMock

from decision_hub.infra.database import (
    _escape_like,
    batch_update_github_repo_metadata,
    batch_update_github_stars,
)


def _compile_where(stmt) -> str:
    """Render a SQLAlchemy statement's WHERE clause with bound literals."""
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


class TestBatchUpdateGithubStars:
    def test_no_op_on_empty_input(self):
        conn = MagicMock()
        batch_update_github_stars(conn, {})
        conn.execute.assert_not_called()

    def test_underscore_in_repo_url_is_escaped(self):
        conn = MagicMock()
        batch_update_github_stars(
            conn,
            {"https://github.com/pymc_labs/decision-hub": 42},
        )
        assert conn.execute.call_count == 1
        rendered = _compile_where(conn.execute.call_args.args[0])
        # The rendered LIKE pattern must contain the escaped underscore
        # (i.e. the escape character preceding it) so a repo like
        # ``pymcXlabs`` cannot match by wildcard.
        assert _escape_like("https://github.com/pymc_labs/decision-hub") + "/%" in rendered
        # And the ESCAPE clause must be present so Postgres knows to honour it.
        assert "ESCAPE" in rendered.upper()

    def test_percent_in_repo_url_is_escaped(self):
        conn = MagicMock()
        batch_update_github_stars(conn, {"https://github.com/foo/100%bar": 7})
        rendered = _compile_where(conn.execute.call_args.args[0])
        # Escaped percent should be present in the LIKE pattern
        assert "\\%" in rendered

    def test_one_update_per_repo(self):
        conn = MagicMock()
        batch_update_github_stars(
            conn,
            {
                "https://github.com/a/one": 1,
                "https://github.com/b/two": 2,
                "https://github.com/c/three": 3,
            },
        )
        assert conn.execute.call_count == 3


class TestBatchUpdateGithubRepoMetadata:
    def test_no_op_on_empty_input(self):
        conn = MagicMock()
        batch_update_github_repo_metadata(conn, {})
        conn.execute.assert_not_called()

    def test_underscore_in_repo_url_is_escaped(self):
        conn = MagicMock()
        batch_update_github_repo_metadata(
            conn,
            {
                "https://github.com/pymc_labs/decision-hub": {
                    "forks": 3,
                    "watchers": 4,
                    "is_archived": False,
                    "license": "MIT",
                }
            },
        )
        rendered = _compile_where(conn.execute.call_args.args[0])
        assert _escape_like("https://github.com/pymc_labs/decision-hub") + "/%" in rendered
        assert "ESCAPE" in rendered.upper()
