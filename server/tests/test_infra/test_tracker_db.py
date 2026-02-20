"""Database function tests for skill trackers.

These tests use mocked connections since real DB tests require
the migrate-check CI pipeline.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from decision_hub.infra.database import (
    _row_to_skill_tracker,
    claim_due_trackers,
    delete_skill_tracker,
    find_skill_tracker,
    insert_skill_tracker,
    list_skill_trackers_for_user,
    update_skill_tracker,
)
from decision_hub.models import SkillTracker


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
