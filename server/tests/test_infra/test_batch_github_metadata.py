"""Tests for the batched GitHub metadata UPDATEs in infra.database.

These functions used to issue one UPDATE per repo URL, which is the most
frequent DB workload on this codebase (every crawler/tracker poll).  The
batched implementation issues a single UPDATE driven by a VALUES table.
"""

from unittest.mock import MagicMock

import sqlalchemy as sa

from decision_hub.infra.database import (
    batch_update_github_repo_metadata,
    batch_update_github_stars,
)


def _captured_statements(conn: MagicMock) -> list[sa.sql.Executable]:
    """Return the SQL statements the function passed to conn.execute()."""
    return [call.args[0] for call in conn.execute.call_args_list]


class TestBatchUpdateGithubStars:
    def test_empty_input_skips_db_round_trip(self):
        conn = MagicMock()
        batch_update_github_stars(conn, {})
        conn.execute.assert_not_called()

    def test_issues_exactly_one_update_for_many_repos(self):
        """Three repos must collapse into a single UPDATE."""
        conn = MagicMock()
        batch_update_github_stars(
            conn,
            {
                "https://github.com/a/one": 1,
                "https://github.com/b/two": 2,
                "https://github.com/c/three": 3,
            },
        )
        assert conn.execute.call_count == 1
        stmt = _captured_statements(conn)[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        # Verify it's an UPDATE on skills with a derived VALUES table and that
        # every repo URL flows through bound parameters (no N updates).
        assert compiled.startswith("UPDATE skills")
        assert "github_stars" in compiled
        for url in ("a/one", "b/two", "c/three"):
            assert url in compiled


class TestBatchUpdateGithubRepoMetadata:
    def test_empty_input_skips_db_round_trip(self):
        conn = MagicMock()
        batch_update_github_repo_metadata(conn, {})
        conn.execute.assert_not_called()

    def test_issues_exactly_one_update_for_many_repos(self):
        conn = MagicMock()
        batch_update_github_repo_metadata(
            conn,
            {
                "https://github.com/a/one": {
                    "forks": 1,
                    "watchers": 10,
                    "is_archived": False,
                    "license": "MIT",
                },
                "https://github.com/b/two": {
                    "forks": 2,
                    "watchers": 20,
                    "is_archived": True,
                    "license": "Apache-2.0",
                },
            },
        )
        assert conn.execute.call_count == 1
        stmt = _captured_statements(conn)[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert compiled.startswith("UPDATE skills")
        for field in ("github_forks", "github_watchers", "github_is_archived", "github_license"):
            assert field in compiled
        for url in ("a/one", "b/two"):
            assert url in compiled

    def test_tolerates_missing_metadata_keys(self):
        """Partial metadata dicts must not crash — missing keys become NULL."""
        conn = MagicMock()
        batch_update_github_repo_metadata(
            conn,
            {"https://github.com/a/one": {"forks": 1}},
        )
        assert conn.execute.call_count == 1
