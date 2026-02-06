"""Tests for dhub.cli.org -- organization management commands."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(response: MagicMock) -> MagicMock:
    """Return a mock httpx.Client usable as a context manager."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post.return_value = response
    client.get.return_value = response
    return client


def _ok_response(json_data: dict | list | None = None, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# org list
# ---------------------------------------------------------------------------

class TestListOrgs:

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.org.httpx.Client")
    def test_list_orgs_with_results(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        orgs = [
            {"slug": "alpha-org"},
            {"slug": "beta-org"},
        ]
        mock_client_cls.return_value = _make_mock_client(_ok_response(orgs))

        result = runner.invoke(app, ["org", "list"])

        assert result.exit_code == 0
        assert "alpha-org" in result.output
        assert "beta-org" in result.output

        # Verify the HTTP call was made (without asserting exact headers,
        # since build_headers includes a dynamic client version).
        mock_client = mock_client_cls.return_value.__enter__()
        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args
        assert "/v1/orgs" in call_kwargs.args[0]
        headers = call_kwargs.kwargs.get("headers", {})
        assert "Authorization" in headers

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.org.httpx.Client")
    def test_list_orgs_empty(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        mock_client_cls.return_value = _make_mock_client(_ok_response([]))

        result = runner.invoke(app, ["org", "list"])

        assert result.exit_code == 0
        assert "No namespaces available" in result.output
