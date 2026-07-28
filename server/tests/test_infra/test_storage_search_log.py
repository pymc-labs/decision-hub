"""Tests for the search-log storage helpers.

Focus: ``build_search_log_key`` was extracted from ``upload_search_log`` so
callers can persist the key to the DB *before* the S3 upload runs — closing
the window where a failed insert leaves an orphan blob under ``search-logs/``.
The two functions must agree on the key format or the orphan-avoidance
guarantee breaks silently.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from decision_hub.infra.storage import build_search_log_key, upload_search_log


class TestBuildSearchLogKey:
    def test_format_matches_upload_search_log(self) -> None:
        """upload_search_log delegates to build_search_log_key. If the two
        ever diverge, insert_search_log's stored s3_key won't match the
        blob's actual key — silently breaking every reverse lookup.
        """
        log_id = uuid4()
        s3 = MagicMock()

        returned_key = upload_search_log(s3, "bucket", log_id, "q", "a", {})
        precomputed = build_search_log_key(log_id)

        assert returned_key == precomputed

    def test_key_shape(self) -> None:
        """Key uses ``search-logs/{yyyy-mm-dd}/{log_id}.json`` so lifecycle
        rules and monthly-cost queries can bucket by date prefix."""
        log_id = uuid4()
        key = build_search_log_key(log_id)
        assert key.startswith("search-logs/")
        assert key.endswith(f"/{log_id}.json")
        # yyyy-mm-dd is exactly 10 chars between the prefix and log id
        date_part = key.split("/")[1]
        assert len(date_part) == 10
        assert date_part[4] == "-" and date_part[7] == "-"
