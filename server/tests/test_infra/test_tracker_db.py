"""Database function tests for skill trackers and tracker metrics.

These tests use mocked connections since real DB tests require
the migrate-check CI pipeline.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from decision_hub.infra.database import (
    _row_to_skill_tracker,
    _row_to_tracker_metrics,
    batch_clear_tracker_errors,
    batch_defer_trackers,
    batch_disable_trackers,
    batch_set_tracker_errors,
    claim_due_trackers,
    delete_skill_tracker,
    find_skill_tracker,
    insert_skill_tracker,
    insert_tracker_metrics,
    list_skill_trackers_for_user,
    list_tracker_metrics,
    mark_skills_source_removed,
    update_skill_tracker,
)
from decision_hub.models import SkillTracker, TrackerMetrics


def _make_tracker_row(
    tracker_id: UUID | None = None,
    user_id: UUID | None = None,
    enabled: bool = True,
    last_error: str | None = None,
    next_check_at: datetime | None = None,
) -> MagicMock:
    """Create a mock row that simulates a skill_trackers row."""
    row = MagicMock()
    row.id = tracker_id or uuid4()
    row.user_id = user_id or uuid4()
    row.org_slug = "test-org"
    row.repo_url = "https://github.com/owner/repo"
    row.branch = "main"
    row.last_commit_sha = None
    row.poll_interval_minutes = 60
    row.enabled = enabled
    row.last_checked_at = None
    row.last_published_at = None
    row.last_error = last_error
    row.next_check_at = next_check_at
    row.created_at = datetime.now(UTC)
    return row


class TestRowToSkillTracker:
    def test_maps_all_fields(self):
        row = _make_tracker_row()
        tracker = _row_to_skill_tracker(row)
        assert isinstance(tracker, SkillTracker)
        assert tracker.id == row.id
        assert tracker.user_id == row.user_id
        assert tracker.org_slug == "test-org"
        assert tracker.repo_url == "https://github.com/owner/repo"
        assert tracker.branch == "main"
        assert tracker.enabled is True
        assert tracker.next_check_at is None

    def test_maps_next_check_at(self):
        now = datetime.now(UTC)
        row = _make_tracker_row(next_check_at=now)
        tracker = _row_to_skill_tracker(row)
        assert tracker.next_check_at == now


class TestInsertSkillTracker:
    def test_insert_returns_tracker(self):
        conn = MagicMock()
        row = _make_tracker_row()
        conn.execute.return_value.one.return_value = row

        result = insert_skill_tracker(
            conn,
            user_id=row.user_id,
            org_slug="test-org",
            repo_url="https://github.com/owner/repo",
        )
        assert isinstance(result, SkillTracker)
        assert result.org_slug == "test-org"
        conn.execute.assert_called_once()

    def test_insert_duplicate_raises(self):
        from sqlalchemy.exc import IntegrityError

        conn = MagicMock()
        conn.execute.side_effect = IntegrityError("duplicate", {}, Exception())

        with pytest.raises(IntegrityError):
            insert_skill_tracker(
                conn,
                user_id=uuid4(),
                org_slug="test-org",
                repo_url="https://github.com/owner/repo",
            )


class TestFindSkillTracker:
    def test_find_existing(self):
        conn = MagicMock()
        row = _make_tracker_row()
        conn.execute.return_value.first.return_value = row

        result = find_skill_tracker(conn, row.id)
        assert result is not None
        assert result.id == row.id

    def test_find_not_found(self):
        conn = MagicMock()
        conn.execute.return_value.first.return_value = None

        result = find_skill_tracker(conn, uuid4())
        assert result is None


class TestListSkillTrackersForUser:
    def test_list_returns_trackers(self):
        conn = MagicMock()
        user_id = uuid4()
        rows = [_make_tracker_row(user_id=user_id) for _ in range(3)]
        conn.execute.return_value.all.return_value = rows

        result = list_skill_trackers_for_user(conn, user_id)
        assert len(result) == 3
        assert all(isinstance(t, SkillTracker) for t in result)


class TestUpdateSkillTracker:
    def test_clears_error(self):
        conn = MagicMock()
        tracker_id = uuid4()

        update_skill_tracker(conn, tracker_id, last_error=None)
        conn.execute.assert_called_once()

    def test_sentinel_pattern_no_change(self):
        """When last_error is not passed (defaults to ...), it should not be updated."""
        conn = MagicMock()
        tracker_id = uuid4()

        # Only update enabled, not last_error
        update_skill_tracker(conn, tracker_id, enabled=True)
        conn.execute.assert_called_once()

    def test_no_values_skips_update(self):
        conn = MagicMock()
        tracker_id = uuid4()

        update_skill_tracker(conn, tracker_id)
        conn.execute.assert_not_called()


class TestClaimDueTrackers:
    def test_returns_claimed_trackers(self):
        conn = MagicMock()
        rows = [_make_tracker_row() for _ in range(3)]
        conn.execute.return_value.all.return_value = rows

        result = claim_due_trackers(conn, batch_size=100)
        assert len(result) == 3
        assert all(isinstance(t, SkillTracker) for t in result)

    def test_batch_size_is_passed_to_query(self):
        """Verify that the SQL query includes a LIMIT clause derived from batch_size."""
        conn = MagicMock()
        conn.execute.return_value.all.return_value = []

        claim_due_trackers(conn, batch_size=42)

        # The UPDATE statement is the one executed; verify it was called
        conn.execute.assert_called_once()
        # Compile the statement and check LIMIT is present
        stmt = conn.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "42" in compiled

    def test_returns_empty_when_none_due(self):
        conn = MagicMock()
        conn.execute.return_value.all.return_value = []

        result = claim_due_trackers(conn, batch_size=100)
        assert result == []

    def test_jitter_adds_random_to_query(self):
        """When jitter_seconds > 0, the SQL should include random()."""
        conn = MagicMock()
        conn.execute.return_value.all.return_value = []

        claim_due_trackers(conn, batch_size=10, jitter_seconds=120)

        conn.execute.assert_called_once()
        stmt = conn.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "random()" in compiled

    def test_no_jitter_excludes_random(self):
        """When jitter_seconds=0, the SQL should NOT include random()."""
        conn = MagicMock()
        conn.execute.return_value.all.return_value = []

        claim_due_trackers(conn, batch_size=10, jitter_seconds=0)

        conn.execute.assert_called_once()
        stmt = conn.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "random()" not in compiled


class TestDeleteSkillTracker:
    def test_delete_existing(self):
        conn = MagicMock()
        conn.execute.return_value.rowcount = 1

        result = delete_skill_tracker(conn, uuid4())
        assert result is True

    def test_delete_not_found(self):
        conn = MagicMock()
        conn.execute.return_value.rowcount = 0

        result = delete_skill_tracker(conn, uuid4())
        assert result is False


# ---------------------------------------------------------------------------
# Batch tracker update tests
# ---------------------------------------------------------------------------


class TestBatchClearTrackerErrors:
    def test_empty_list_skips_db(self):
        conn = MagicMock()
        result = batch_clear_tracker_errors(conn, [])
        assert result == 0
        conn.execute.assert_not_called()

    def test_non_empty_calls_execute(self):
        conn = MagicMock()
        conn.execute.return_value.rowcount = 3
        ids = [uuid4() for _ in range(3)]

        result = batch_clear_tracker_errors(conn, ids)
        assert result == 3
        conn.execute.assert_called_once()


class TestBatchSetTrackerErrors:
    def test_empty_list_skips_db(self):
        conn = MagicMock()
        result = batch_set_tracker_errors(conn, [], "some error")
        assert result == 0
        conn.execute.assert_not_called()

    def test_non_empty_calls_execute(self):
        conn = MagicMock()
        conn.execute.return_value.rowcount = 2
        ids = [uuid4() for _ in range(2)]

        result = batch_set_tracker_errors(conn, ids, "GraphQL: repo not found")
        assert result == 2
        conn.execute.assert_called_once()


class TestBatchDeferTrackers:
    def test_empty_list_skips_db(self):
        conn = MagicMock()
        result = batch_defer_trackers(conn, [], "deferred")
        assert result == 0
        conn.execute.assert_not_called()

    def test_non_empty_calls_execute(self):
        conn = MagicMock()
        conn.execute.return_value.rowcount = 4
        ids = [uuid4() for _ in range(4)]

        result = batch_defer_trackers(conn, ids, "rate_limit: deferred")
        assert result == 4
        conn.execute.assert_called_once()


class TestBatchDisableTrackers:
    def test_empty_list_skips_db(self):
        conn = MagicMock()
        result = batch_disable_trackers(conn, [])
        assert result == 0
        conn.execute.assert_not_called()

    def test_non_empty_calls_execute(self):
        conn = MagicMock()
        conn.execute.return_value.rowcount = 3
        ids = [uuid4() for _ in range(3)]

        result = batch_disable_trackers(conn, ids)
        assert result == 3
        conn.execute.assert_called_once()


class TestMarkSkillsSourceRemoved:
    def test_empty_list_skips_db(self):
        conn = MagicMock()
        result = mark_skills_source_removed(conn, [])
        assert result == 0
        conn.execute.assert_not_called()

    def test_non_empty_calls_execute(self):
        conn = MagicMock()
        conn.execute.return_value.rowcount = 2
        urls = ["https://github.com/owner/repo1", "https://github.com/owner/repo2"]

        result = mark_skills_source_removed(conn, urls)
        assert result == 2
        conn.execute.assert_called_once()


# ---------------------------------------------------------------------------
# Tracker metrics tests
# ---------------------------------------------------------------------------


def _make_metrics_row(
    recorded_at: datetime | None = None,
    total_checked: int = 42,
    github_rate_remaining: int | None = 4800,
) -> MagicMock:
    """Create a mock row that simulates a tracker_metrics row."""
    row = MagicMock()
    row.id = uuid4()
    row.recorded_at = recorded_at or datetime.now(UTC)
    row.iterations = 2
    row.total_checked = total_checked
    row.trackers_due = 10
    row.trackers_unchanged = 8
    row.trackers_changed = 2
    row.trackers_errored = 0
    row.trackers_processed = 2
    row.trackers_failed = 0
    row.skipped_rate_limit = 0
    row.github_rate_remaining = github_rate_remaining
    row.batch_duration_seconds = 3.2
    return row


class TestRowToTrackerMetrics:
    def test_maps_all_fields(self):
        row = _make_metrics_row()
        metrics = _row_to_tracker_metrics(row)
        assert isinstance(metrics, TrackerMetrics)
        assert metrics.id == row.id
        assert metrics.total_checked == 42
        assert metrics.trackers_changed == 2
        assert metrics.github_rate_remaining == 4800
        assert metrics.batch_duration_seconds == 3.2

    def test_maps_none_rate(self):
        row = _make_metrics_row(github_rate_remaining=None)
        metrics = _row_to_tracker_metrics(row)
        assert metrics.github_rate_remaining is None


class TestInsertTrackerMetrics:
    def test_insert_returns_metrics(self):
        conn = MagicMock()
        row = _make_metrics_row()
        conn.execute.return_value.one.return_value = row

        result = insert_tracker_metrics(
            conn,
            iterations=2,
            total_checked=42,
            trackers_due=10,
            trackers_unchanged=8,
            trackers_changed=2,
            trackers_errored=0,
            trackers_processed=2,
            trackers_failed=0,
            skipped_rate_limit=0,
            github_rate_remaining=4800,
            batch_duration_seconds=3.2,
        )
        assert isinstance(result, TrackerMetrics)
        assert result.total_checked == 42
        conn.execute.assert_called_once()


class TestListTrackerMetrics:
    def test_list_returns_metrics(self):
        conn = MagicMock()
        rows = [_make_metrics_row() for _ in range(3)]
        conn.execute.return_value.all.return_value = rows

        result = list_tracker_metrics(conn, limit=10)
        assert len(result) == 3
        assert all(isinstance(m, TrackerMetrics) for m in result)

    def test_list_empty(self):
        conn = MagicMock()
        conn.execute.return_value.all.return_value = []

        result = list_tracker_metrics(conn)
        assert result == []
