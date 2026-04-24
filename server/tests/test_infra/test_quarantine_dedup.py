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

    def test_query_has_deterministic_order_by_with_tiebreaker(self):
        """LIMIT 1 must be paired with ORDER BY including a unique
        tiebreaker (id) so multiple F-grade rows with identical
        created_at yield deterministic results across replicas."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.scalar_one_or_none.return_value = None

        has_recent_quarantine(
            mock_conn,
            org_slug="myorg",
            skill_name="my-skill",
            checksum="abc123",
            max_age_hours=24,
        )

        # Stringify using the default dialect (bind params render as
        # :name); we only care about ORDER BY / LIMIT shape.
        stmt = mock_conn.execute.call_args[0][0]
        compiled = str(stmt)
        assert "ORDER BY" in compiled
        assert "created_at DESC" in compiled
        assert "id DESC" in compiled
        assert "LIMIT" in compiled
