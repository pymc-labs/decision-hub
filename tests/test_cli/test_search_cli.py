"""Tests for decision_hub.cli.search -- ask command."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from decision_hub.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(response: MagicMock) -> MagicMock:
    """Return a mock httpx.Client usable as a context manager."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get.return_value = response
    return client


def _ok_response(json_data: dict | None = None, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


def _error_response(status_code: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# ask_command tests
# ---------------------------------------------------------------------------

class TestAskCommand:

    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.search.httpx.Client")
    def test_ask_success(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        mock_client_cls.return_value = _make_mock_client(
            _ok_response({
                "query": "analyze A/B test results",
                "results": "Found 3 matching skills:\n- ab-test-analyzer\n- stats-runner\n- experiment-tools",
            })
        )

        result = runner.invoke(app, ["ask", "analyze A/B test results"])

        assert result.exit_code == 0
        assert "analyze A/B test results" in result.output
        assert "ab-test-analyzer" in result.output

    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.search.httpx.Client")
    def test_ask_503_not_configured(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        mock_client_cls.return_value = _make_mock_client(_error_response(503))

        result = runner.invoke(app, ["ask", "some query"])

        assert result.exit_code == 1
        assert "not available" in result.output.lower()

    def test_ask_empty_query(self) -> None:
        """Typer should reject a missing query argument."""
        result = runner.invoke(app, ["ask"])

        # Typer exits with code 2 for missing required arguments
        assert result.exit_code == 2
        assert "Missing argument" in result.output
