"""Tests for the CLI track subcommand helpers."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from dhub.cli.track import _resolve_tracker_id


class TestResolveTrackerId:
    def test_full_uuid_returned_directly(self):
        full_id = "12345678-1234-5678-1234-567812345678"
        result = _resolve_tracker_id("http://api", {}, full_id)
        assert result == full_id

    @patch("dhub.cli.track.httpx.Client")
    def test_prefix_match(self, mock_client_cls):
        tracker_id = str(uuid4())
        prefix = tracker_id[:8]

        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"id": tracker_id},
            {"id": str(uuid4())},
        ]
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        result = _resolve_tracker_id("http://api", {}, prefix)
        assert result == tracker_id

    @patch("dhub.cli.track.httpx.Client")
    def test_no_match(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"id": str(uuid4())},
        ]
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        result = _resolve_tracker_id("http://api", {}, "xxxxxxxx")
        assert result is None

    @patch("dhub.cli.track.httpx.Client")
    def test_ambiguous_prefix(self, mock_client_cls):
        # Two trackers with the same prefix
        shared_prefix = "abcdef"
        id1 = f"{shared_prefix}12-1234-5678-1234-567812345678"
        id2 = f"{shared_prefix}34-1234-5678-1234-567812345678"

        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"id": id1},
            {"id": id2},
        ]
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        result = _resolve_tracker_id("http://api", {}, shared_prefix)
        assert result is None
