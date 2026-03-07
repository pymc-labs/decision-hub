"""Tests for fetch_paginated_plugins total count on empty pages."""

from unittest.mock import MagicMock

from decision_hub.infra.database import fetch_paginated_plugins


class TestFetchPaginatedPluginsTotal:
    """Verify total count is preserved when the requested page is empty."""

    def test_total_from_window_function_when_rows_exist(self):
        """When rows are returned, total comes from the window function."""
        mock_row = MagicMock()
        mock_row.total_count = 42
        mock_row._mapping = {
            "org_slug": "acme",
            "plugin_name": "my-plugin",
            "description": "A plugin",
            "download_count": 0,
            "category": "testing",
            "platforms": ["claude"],
            "skill_count": 1,
            "hook_count": 0,
            "agent_count": 0,
            "command_count": 0,
            "author_name": "Test",
            "source_repo_url": None,
            "github_stars": None,
            "github_license": None,
            "latest_version": "1.0.0",
            "eval_status": "A",
            "gauntlet_summary": None,
            "published_at": None,
            "published_by": "testuser",
            "has_tracker": False,
            "total_count": 42,
        }

        conn = MagicMock()
        conn.execute.return_value.all.return_value = [mock_row]

        rows, total = fetch_paginated_plugins(conn, limit=20, offset=0)

        assert total == 42
        assert len(rows) == 1
        # total_count should be stripped from the row dicts
        assert "total_count" not in rows[0]

    def test_fallback_count_when_page_is_empty(self):
        """When offset is past the end, total is obtained via fallback count query."""
        conn = MagicMock()

        # First call: main query returns no rows (empty page)
        empty_result = MagicMock()
        empty_result.all.return_value = []

        # Second call: fallback count returns the real total
        count_result = MagicMock()
        count_result.scalar.return_value = 15

        conn.execute.side_effect = [empty_result, count_result]

        rows, total = fetch_paginated_plugins(conn, limit=20, offset=9999)

        assert rows == []
        assert total == 15
        # Two queries should have been executed: main + fallback count
        assert conn.execute.call_count == 2

    def test_fallback_count_returns_zero_when_no_plugins_exist(self):
        """When no plugins match at all, fallback count returns 0."""
        conn = MagicMock()

        empty_result = MagicMock()
        empty_result.all.return_value = []

        count_result = MagicMock()
        count_result.scalar.return_value = 0

        conn.execute.side_effect = [empty_result, count_result]

        rows, total = fetch_paginated_plugins(conn, limit=20, offset=0)

        assert rows == []
        assert total == 0
