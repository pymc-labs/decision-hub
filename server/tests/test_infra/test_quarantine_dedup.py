"""Tests for quarantine checksum dedup query."""

from unittest.mock import MagicMock

from decision_hub.infra.database import has_recent_quarantine


class TestHasRecentQuarantine:
    def test_returns_true_when_matching_quarantine_exists(self):
        """A recent F-grade audit log with matching checksum should return True."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.scalar_one_or_none.return_value = 1

        result = has_recent_quarantine(
            mock_conn,
            org_slug="myorg",
            skill_name="my-skill",
            checksum="abc123",
            max_age_hours=24,
        )
        assert result is True

    def test_returns_false_when_no_match(self):
        """No matching quarantine should return False."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.scalar_one_or_none.return_value = None

        result = has_recent_quarantine(
            mock_conn,
            org_slug="myorg",
            skill_name="my-skill",
            checksum="abc123",
            max_age_hours=24,
        )
        assert result is False

    def test_returns_false_when_max_age_is_zero(self):
        """max_age_hours=0 disables the skip — always returns False."""
        mock_conn = MagicMock()

        result = has_recent_quarantine(
            mock_conn,
            org_slug="myorg",
            skill_name="my-skill",
            checksum="abc123",
            max_age_hours=0,
        )
        assert result is False
        mock_conn.execute.assert_not_called()
