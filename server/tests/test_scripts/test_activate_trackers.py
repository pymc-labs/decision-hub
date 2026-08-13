"""Regression tests for `scripts.activate_trackers` insert loop.

The historical bug: the script opened a single `engine.connect()` around
the entire insert loop and called `conn.rollback()` on any `IntegrityError`.
Because `engine.connect()` opens ONE implicit transaction, rollback
discards every prior successful insert — the trailing `conn.commit()` then
only persists rows inserted AFTER the last rollback. The user sees
"Created N" but the DB only holds a suffix.

These tests verify that a mid-loop IntegrityError does not undo prior
successful inserts.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from decision_hub.scripts import activate_trackers


class TestInsertLoopIsolation:
    """The insert loop must commit each row in its own transaction."""

    def test_prior_inserts_survive_mid_loop_integrity_error(self, monkeypatch, capsys):
        """When row 2 hits IntegrityError, rows 1 and 3 must both be committed."""
        crawler_user_id = uuid4()
        missing = [
            ("https://github.com/org/repo1", "org"),
            ("https://github.com/org/repo2", "org"),  # will collide
            ("https://github.com/org/repo3", "org"),
        ]

        # Track which insert_skill_tracker calls actually happened.
        call_log: list[str] = []
        # Track each `engine.begin()` context — its __exit__ commits, an
        # exception inside triggers rollback of ONLY that transaction.
        begin_calls: list[MagicMock] = []

        def fake_insert(conn, *, user_id, org_slug, repo_url):
            call_log.append(repo_url)
            if repo_url.endswith("repo2"):
                # Simulate unique-constraint collision on the second row.
                raise IntegrityError("stmt", {}, Exception("duplicate key"))

        fake_engine = MagicMock()

        def fake_begin():
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=MagicMock())
            ctx.__exit__ = MagicMock(return_value=False)
            begin_calls.append(ctx)
            return ctx

        fake_engine.begin.side_effect = fake_begin
        fake_engine.connect.return_value.__enter__.return_value = MagicMock()

        fake_settings = MagicMock()
        fake_settings.database_url = "postgresql://test"

        monkeypatch.setattr(activate_trackers, "create_settings", lambda: fake_settings)
        monkeypatch.setattr(activate_trackers, "create_engine", lambda url: fake_engine)
        monkeypatch.setattr(activate_trackers, "_find_crawler_user_id", lambda conn: crawler_user_id)
        monkeypatch.setattr(activate_trackers, "_find_repos_without_trackers", lambda conn, uid: missing)
        monkeypatch.setattr(activate_trackers, "insert_skill_tracker", fake_insert)

        # Simulate argv without --dry-run — script runs to completion, no sys.exit.
        with patch("sys.argv", ["activate_trackers"]):
            activate_trackers._run()

        # All three rows were attempted:
        assert call_log == [
            "https://github.com/org/repo1",
            "https://github.com/org/repo2",
            "https://github.com/org/repo3",
        ]
        # Three separate transactions were opened (one per row):
        assert fake_engine.begin.call_count == 3
        # Output shows created=2, skipped=1 — the prior insert survived.
        out = capsys.readouterr().out
        assert "Created 2 trackers, skipped 1" in out
