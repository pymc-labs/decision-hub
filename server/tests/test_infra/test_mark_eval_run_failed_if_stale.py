"""Unit tests for mark_eval_run_failed_if_stale atomic update.

The helper exists specifically to avoid a read-check-update race where a
worker emits a fresh heartbeat between the caller's observation of a
stale heartbeat and the status flip.  These tests verify the SQL shape
without needing a real database.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from decision_hub.infra.database import mark_eval_run_failed_if_stale


class TestMarkEvalRunFailedIfStale:
    def test_returns_true_when_row_updated(self):
        """If the conditional UPDATE affects a row, the helper returns True."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.rowcount = 1

        observed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = mark_eval_run_failed_if_stale(
            mock_conn,
            uuid4(),
            observed_heartbeat_at=observed,
            error_message="Stale heartbeat",
            completed_at=datetime(2026, 1, 1, 12, 5, 0, tzinfo=UTC),
        )

        assert result is True
        mock_conn.execute.assert_called_once()

    def test_returns_false_when_row_was_updated_concurrently(self):
        """If another transaction updated heartbeat_at first, rowcount is 0."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.rowcount = 0

        result = mark_eval_run_failed_if_stale(
            mock_conn,
            uuid4(),
            observed_heartbeat_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            error_message="Stale heartbeat",
            completed_at=datetime(2026, 1, 1, 12, 5, 0, tzinfo=UTC),
        )

        assert result is False

    def test_update_is_gated_on_observed_heartbeat(self):
        """The UPDATE's WHERE must include heartbeat_at == observed so a
        fresh heartbeat from a live worker doesn't get clobbered."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.rowcount = 1

        observed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        mark_eval_run_failed_if_stale(
            mock_conn,
            uuid4(),
            observed_heartbeat_at=observed,
            error_message="Stale heartbeat",
            completed_at=datetime(2026, 1, 1, 12, 5, 0, tzinfo=UTC),
        )

        stmt = mock_conn.execute.call_args[0][0]
        compiled = str(stmt)
        assert "UPDATE eval_runs" in compiled
        # Guard clauses appear in the WHERE: the observed heartbeat and
        # the active-worker status set must both be present.
        assert "heartbeat_at" in compiled
        assert "status IN" in compiled
